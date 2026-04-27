import os
import re
import json
import time as _time
import sys
import shutil
import logging
import yaml
import inspect
from src.config import (
    LLM_API_KEY, DASHSCOPE_API_KEY, API_KEYS,
    CACHE_DIR, PIC_DIR, OUTPUT_DIR, FONT_PATH,
)
from src.llm_tools.prompts import prompts_dict
from src.utils.title_cleaner import sanitize_generated_title
from src.utils.text_helpers import first_chinese_index

# 配置日志记录
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ---------------------------------------------------------------------------
# 延迟初始化：避免模块导入时触发 API 连接等副作用
# ---------------------------------------------------------------------------

_initialized = False

_PLAN_SECTIONS = ("opening", "intro", "method", "results")
MANUALLY_EXTRACT_IMAGES = False
model = None
client = None


def _ensure_initialized():
    """延迟初始化 LLM 客户端，首次调用时执行，后续跳过。"""
    global _initialized, MANUALLY_EXTRACT_IMAGES, model, client
    if _initialized:
        return

    import dashscope
    from openai import OpenAI

    MANUALLY_EXTRACT_IMAGES = False
    MODEL = 'deepseek'

    config_path = "config.yaml"
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    # 解析 LLM API Key
    api_key = LLM_API_KEY or config.get("llm_api_key")
    if not api_key:
        raise ValueError("请在 config.yaml 或环境变量 LLM_API_KEY 中设置 API Key")

    # 解析 DashScope API Key
    ds_key = DASHSCOPE_API_KEY or config.get("dashscope_api_key")
    if ds_key:
        dashscope.api_key = ds_key

    if MODEL == 'qwen':
        model = 'qwen-max'
        url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        client = OpenAI(api_key=ds_key, base_url=url)
    elif MODEL == 'deepseek':
        model = 'deepseek-chat'
        url = 'https://api.deepseek.com/v1'
        client = OpenAI(api_key=api_key, base_url=url)

    logging.info("LLM 客户端初始化完成: model=%s", model)
    os.makedirs("./cache", exist_ok=True)
    _initialized = True


def _parse_json_response(raw: str):
    """尝试从 LLM 返回中解析 JSON 对象。支持 markdown 代码围栏与截断修复。"""
    if not raw:
        return {}
    s = raw.strip()
    if s.startswith('```'):
        nl = s.find('\n')
        if nl != -1:
            s = s[nl + 1:]
        if s.rstrip().endswith('```'):
            s = s.rstrip()[:-3].rstrip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{.*\}', s, re.S)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logging.warning('无法解析为 JSON: %s', raw[:2000])
    return {}

def get_prompt(func_name, text=None):
    """
    根据函数名称从 prompts_dict 中获取对应的 prompt。
    如果提供了 text，则将 text 附加到 prompt 后。
    """
    prompt = prompts_dict.get(func_name, "")
    if not prompt:
        logging.warning(f"未找到函数 {func_name} 对应的 prompt")
    if text:
        prompt += text
    return prompt


def generate_summary(text, word_budget: int = 1000):
    prompt_template = prompts_dict.get(inspect.currentframe().f_code.co_name, "")
    prompt = prompt_template.format(word_budget=word_budget) + text
    return create_chat_completion(prompt)

def generate_short_summary(text, word_budget: int = 120):
    prompt_template = prompts_dict.get(inspect.currentframe().f_code.co_name, "")
    prompt = prompt_template.format(word_budget=word_budget) + text
    return create_chat_completion(prompt)

def generate_video_title(text):
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    ret_str = create_chat_completion(prompt, text)
    ret_str = sanitize_generated_title(ret_str)
    # 确保英文论文名后有冒号分隔：找到第一个中文字符位置，在其前插入": "
    if ret_str and ':' not in ret_str and '：' not in ret_str:
        idx = first_chinese_index(ret_str)
        if idx > 0:
            ret_str = ret_str[:idx].rstrip() + ': ' + ret_str[idx:]
    return ret_str

def generate_origin_title(text):
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    return create_chat_completion(prompt, text)

def generate_video_proceedings(text):
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    return create_chat_completion(prompt, text)

def _build_paper_meta(text=None, paper_title=None, paper_abstract=None,
                      paper_authors=None, key_points=None, venue=None,
                      github_repo=None) -> dict:
    """从混合输入构造 paper_meta dict（CLI 期望的 schema）。

    优先级：显式 kwargs > text 兜底（取前 1500 字塞进 abstract）。
    """
    meta = {
        "title": (paper_title or "").strip() or "",
        "abstract": (paper_abstract or "").strip() or "",
        "authors": list(paper_authors or []),
        "key_points": list(key_points or []),
    }
    if venue:
        meta["venue"] = str(venue)
    if github_repo:
        meta["github_repo"] = str(github_repo)
    if not meta["abstract"] and text:
        meta["abstract"] = (text or "").strip()[:4000]
    if not meta["title"] and text:
        # 取首行 80 字作为 title 兜底
        first_line = (text or "").strip().splitlines()[0] if text else ""
        meta["title"] = first_line[:80] or "Untitled"
    return meta


def _normalize_skill_plan_to_legacy(plan: dict) -> dict:
    """skill 输出的 5 段 plan(含 conclusion)规整成下游期望的 4 段格式。

    下游(_PLAN_SECTIONS = opening/intro/method/results)只读 script 字段;
    skill 用 text 字段。这里同时兼容两种 key,且把 conclusion 合并到 results 段尾。
    """
    if not isinstance(plan, dict):
        return {}
    out = {}
    for sec in _PLAN_SECTIONS:
        v = plan.get(sec, {})
        if isinstance(v, str):
            v = {"text": v}
        if not isinstance(v, dict):
            continue
        text = (v.get("text") or v.get("script") or "").strip()
        if not text:
            continue
        out[sec] = {
            "script": text,
            "text": text,
        }
        if v.get("duration_sec") is not None:
            out[sec]["duration_sec"] = v.get("duration_sec")
        if v.get("key_points"):
            out[sec]["key_points"] = v.get("key_points")
    # conclusion(skill 多出的第 5 段)拼到 results 段尾，下游 structured_plan_to_text 就能拿到
    conc = plan.get("conclusion") or {}
    if isinstance(conc, str):
        conc = {"text": conc}
    if isinstance(conc, dict):
        conc_text = (conc.get("text") or conc.get("script") or "").strip()
        if conc_text and out.get("results"):
            merged = (out["results"]["script"] + "\n" + conc_text).strip()
            out["results"]["script"] = merged
            out["results"]["text"] = merged
    return out


def _call_video_plan_skill(text=None, paper_title=None, paper_abstract=None,
                           paper_authors=None, target_duration: int = 300,
                           language: str = "zh", timeout_sec: int = 300):
    """以 subprocess 模式调 ``python -m src.llm_tools.cli generate-plan``。

    返回 5 段 plan dict(规整成 legacy script 字段);失败返回空 dict。
    永不抛异常 → 上层调用方自行 fallback。
    """
    import subprocess as _sp
    import tempfile
    import shutil as _shutil

    paper_meta = _build_paper_meta(
        text=text,
        paper_title=paper_title,
        paper_abstract=paper_abstract,
        paper_authors=paper_authors,
    )
    if not paper_meta.get("title") or not paper_meta.get("abstract"):
        logging.warning("[via_skill] paper_meta missing title/abstract; skill skipped")
        return {}

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    tmp_dir = tempfile.mkdtemp(prefix="video_plan_", dir=os.path.join(project_root, "cache") if os.path.isdir(os.path.join(project_root, "cache")) else None)
    meta_path = os.path.join(tmp_dir, "paper_meta.json")
    out_path = os.path.join(tmp_dir, "plan_out.json")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(paper_meta, f, ensure_ascii=False, indent=2)

        env = os.environ.copy()
        # 透传 PYTHONPATH 以便 src.* import 生效
        env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

        cmd = [
            sys.executable, "-m", "src.llm_tools.cli", "generate-plan",
            "--paper-meta", meta_path,
            "--target-duration", str(int(target_duration)),
            "--language", str(language or "zh"),
            "--out", out_path,
        ]
        try:
            r = _sp.run(cmd, capture_output=True, text=True,
                        timeout=timeout_sec, env=env, cwd=project_root)
        except _sp.TimeoutExpired:
            logging.warning("[via_skill] CLI subprocess timeout after %ds", timeout_sec)
            return {}
        except FileNotFoundError as e:
            logging.warning("[via_skill] python binary not found: %s", e)
            return {}
        if r.returncode != 0:
            logging.warning("[via_skill] CLI rc=%d stderr=%s", r.returncode,
                            (r.stderr or "")[-500:])
            # rc=1 但 plan 文件已写入(部分 sections 有效)也接受
        if not os.path.isfile(out_path):
            logging.warning("[via_skill] plan output file not produced")
            return {}
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                raw_plan = json.load(f)
        except Exception as e:  # noqa: BLE001
            logging.warning("[via_skill] plan output parse failed: %s", e)
            return {}
        legacy = _normalize_skill_plan_to_legacy(raw_plan)
        # 至少 4 个 _PLAN_SECTIONS 都得有 script 才算成功
        if not all(isinstance(legacy.get(k), dict) and legacy[k].get("script")
                   for k in _PLAN_SECTIONS):
            logging.warning("[via_skill] skill plan missing required sections, skip")
            return {}
        return legacy
    finally:
        try:
            _shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def generate_structured_video_plan(text=None, word_budget: int = 1000, max_attempts: int = 2,
                                     via_skill: bool = False,
                                     paper_title: str = None,
                                     paper_abstract: str = None,
                                     paper_authors: list = None,
                                     target_duration: int = 300,
                                     language: str = "zh"):
    """生成结构化视频脚本（5段式：opening → intro → method → results → conclusion）。

    Args:
        text: 论文全文(向后兼容,可与 paper_title/paper_abstract 二选一)
        word_budget: 总字数预算(默认 1000,仅 Python 路径用)
        max_attempts: Python 路径重试次数
        via_skill: 显式打开 skill 路径(默认 False);也可设环境变量
                   ``JSR_USE_SKILL_VIDEO_PLAN=1`` 触发
        paper_title / paper_abstract / paper_authors: 显式 paper_meta 字段
        target_duration: 目标视频时长(秒,默认 300,仅 skill 路径用)
        language: 输出语言(默认 zh,仅 skill 路径用)

    Returns:
        dict: opening/intro/method/results 4 段(每段含 script 字段);
              skill 路径会把 conclusion 合并到 results 段尾以保持向后兼容。
              失败返回空 dict。

    路径选择(优先级从高到低):
        1. ``via_skill=True`` 或 ``JSR_USE_SKILL_VIDEO_PLAN=1`` → subprocess 调
           ``src.llm_tools.cli generate-plan``;失败自动 fallback Python 路径
        2. 默认 → 走原 DeepSeek API 单次调用(向后兼容)
    """
    use_skill = bool(via_skill) or os.environ.get("JSR_USE_SKILL_VIDEO_PLAN", "").strip() in ("1", "true", "True")

    if use_skill:
        try:
            plan = _call_video_plan_skill(
                text=text,
                paper_title=paper_title,
                paper_abstract=paper_abstract,
                paper_authors=paper_authors,
                target_duration=int(target_duration or 300),
                language=language or "zh",
            )
            if plan:
                logging.info("[via_skill] video-plan skill succeeded")
                return plan
            logging.warning("[via_skill] skill returned empty, fallback to Python path")
        except Exception as e:  # noqa: BLE001
            logging.warning("[via_skill] skill call crashed, fallback to Python path: %s", e)

    # ---- 默认 / fallback Python 路径(原实现,不动逻辑) ----
    # 兼容新签名: text 为空时,从 paper_title + paper_abstract 拼一段输入文本
    if not text:
        meta = _build_paper_meta(
            paper_title=paper_title, paper_abstract=paper_abstract,
            paper_authors=paper_authors,
        )
        text = (meta.get("title") + "\n\n" + meta.get("abstract")).strip()

    prompt = get_prompt("generate_structured_video_plan")
    prompt = prompt + f"\n总字数预算约{word_budget}字。"
    prompt += "\n严格要求：直接输出 JSON 对象，不要使用 markdown 代码围栏（不要 ```json ... ```），不要任何额外文字。"
    required = _PLAN_SECTIONS
    last_plan = {}
    for attempt in range(max_attempts):
        raw = create_chat_completion(prompt, text, max_tokens=8192)
        plan = _parse_json_response(raw)
        if plan and all(isinstance(plan.get(k), dict) and plan[k].get('script') for k in required):
            return plan
        logging.warning('结构化脚本生成/解析不完整 (第%d次)，重试', attempt + 1)
    logging.warning('结构化脚本生成失败，回退为普通摘要')
    return {}


def structured_plan_to_text(plan: dict) -> str:
    """将结构化脚本转换为连续文本，供 TTS 使用。

    按 opening → intro → method → results 顺序拼接 script 字段。
    """
    if not plan:
        return ""
    sections = list(_PLAN_SECTIONS)
    parts = []
    for section in sections:
        section_data = plan.get(section, {})
        if isinstance(section_data, dict):
            script = section_data.get("script", "")
        elif isinstance(section_data, str):
            script = section_data
        else:
            script = ""
        if script:
            parts.append(script)
    return "\n".join(parts)

def get_paper_demo_website(text):
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    ret = create_chat_completion(prompt, text)

    logging.info(f"{ret}")
    parsed_json = _parse_json_response(ret)
    if not parsed_json:
        logging.warning("未找到 JSON 内容")
        return ''
    logging.info("解析成功: %s", parsed_json)
    # 安全访问 key，防止 KeyError
    state = parsed_json.get('state')
    if state not in ['0', '1', 0, 1]:
        logging.warning("state值不在范围内: %s", state)
        return ''
    if state == '1' or state == 1:
        return parsed_json.get('url', '')
    else:
        logging.warning("未找到视频网址")
        return ''

def create_chat_completion(prompt, user_content=None, max_retries=3, max_tokens=None):
    """调用 LLM 生成内容，自带指数退避重试。"""
    _ensure_initialized()
    messages = [{"role": "system", "content": prompt}]
    if user_content:
        messages.append({"role": "user", "content": user_content})

    for attempt in range(max_retries):
        try:
            kwargs = {"model": model, "messages": messages}
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            wait = 2 ** attempt
            logging.warning(f"LLM 调用失败 (第{attempt+1}次), {wait}s 后重试: {e}")
            if attempt < max_retries - 1:
                _time.sleep(wait)
            else:
                logging.error(f"LLM 调用最终失败: {e}")
                raise

def extract_captions_to_dict(text: str = ''):
    """
    从文本中提取图片和表格标题，返回字典格式
    
    参数:
    - text: 包含图片和表格标题的文本
    
    返回:
    - dict: {"fig_1": "图片标题1", "tab_1": "表格标题1", ...}
    """
    prompt = get_prompt(inspect.currentframe().f_code.co_name, text)
    response = create_chat_completion(prompt, text)
    parsed = _parse_json_response(response)

    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list) and len(parsed) == 2:
        fig_captions, tab_captions = parsed
        out = {}
        for i, caption in enumerate(fig_captions, 1):
            if caption.strip():
                out[f"fig_{i}"] = caption.strip()
        for i, caption in enumerate(tab_captions, 1):
            if caption.strip():
                out[f"tab_{i}"] = caption.strip()
        return out
    logging.error("解析标题失败，LLM返回内容: %s", response[:500])
    return {}


def add_context_to_image_explanations(image_explanations):
    """为图像解释添加上下文和过渡语句

    Args:
        image_explanations: 图像解释列表，每个元素包含detailed_explanation等字段

    Returns:
        list: 添加了context和transition的图像解释列表
    """
    if not image_explanations:
        return image_explanations

    explanations_text = json.dumps(image_explanations, ensure_ascii=False, indent=2)
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    response = create_chat_completion(prompt, explanations_text)

    parsed = _parse_json_response(response)
    if isinstance(parsed, list) and len(parsed) == len(image_explanations):
        logging.info("成功为图像解释添加上下文和过渡语句")
        return parsed
    logging.warning("LLM返回结果无效或长度不符，保持原始解释")
    return image_explanations


def rate_image_importance(captions: list) -> list:
    """对一组图片的题注/描述进行重要性打分。

    Args:
        captions: 图片描述列表

    Returns:
        list[int]: 每张图片的重要性分数（1-10）
    """
    if not captions:
        return []

    captions_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(captions))
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    response = create_chat_completion(prompt, captions_text)

    parsed = _parse_json_response(response)
    scores = parsed.get("scores", [])

    if len(scores) != len(captions):
        logging.warning(f"图片打分结果长度不匹配: 期望 {len(captions)}, 实际 {len(scores)}")
        return [5] * len(captions)

    return [int(s) if isinstance(s, (int, float)) else 5 for s in scores]


def select_top_images(items: list, scores: list, top_n: int = 5) -> list:
    """根据分数选出 top-N 项，保持原始顺序。

    Args:
        items: 待筛选列表
        scores: 对应分数列表
        top_n: 选取数量

    Returns:
        list: 按原始顺序排列的 top-N 项
    """
    if len(items) <= top_n:
        return items[:]

    indexed = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)
    top_indices = sorted([idx for idx, _ in indexed[:top_n]])
    return [items[i] for i in top_indices]
