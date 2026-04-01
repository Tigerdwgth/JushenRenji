import os
import re
import json
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
    """尝试从 LLM 返回中解析 JSON 对象。"""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logging.warning("无法解析为 JSON: %s", raw[:2000])
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

def generate_structured_video_plan(text, word_budget: int = 1000):
    """生成结构化视频脚本（5段式：opening → intro → method → results → conclusion）。

    Returns:
        dict: 包含 opening/intro/method/results 等 key，
              每个 value 包含 script 和 visual_prompt 字段。
              如果解析失败返回空字典。
    """
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    prompt = prompt + f"\n总字数预算约{word_budget}字。"
    raw = create_chat_completion(prompt, text)
    plan = _parse_json_response(raw)
    if not plan:
        logging.warning("结构化脚本生成失败，回退为普通摘要")
    return plan


def structured_plan_to_text(plan: dict) -> str:
    """将结构化脚本转换为连续文本，供 TTS 使用。

    按 opening → intro → method → results 顺序拼接 script 字段。
    """
    if not plan:
        return ""
    sections = ["opening", "intro", "method", "results"]
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

def create_chat_completion(prompt, user_content=None, max_retries=3):
    """调用 LLM 生成内容，自带指数退避重试。"""
    _ensure_initialized()
    import time as _time
    messages = [{"role": "system", "content": prompt}]
    if user_content:
        messages.append({"role": "user", "content": user_content})

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages
            )
            return response.choices[0].message.content
        except Exception as e:
            wait = 2 ** attempt
            logging.warning(f"LLM 调用失败 (第{attempt+1}次), {wait}s 后重试: {e}")
            if attempt < max_retries - 1:
                _time.sleep(wait)
            else:
                logging.error(f"LLM 调用最终失败: {e}")
                raise

def get_captions_from_page(text: str = ''):
    prompt = get_prompt(inspect.currentframe().f_code.co_name, text)
    response = create_chat_completion(prompt, text)

    # 清理LLM返回的内容，移除markdown代码块标记
    cleaned_response = response.strip()
    if cleaned_response.startswith("```json"):
        cleaned_response = cleaned_response[7:]
    if cleaned_response.endswith("```"):
        cleaned_response = cleaned_response[:-3]
    cleaned_response = cleaned_response.strip()

    response2list = json.loads(cleaned_response)
    return response2list

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
    
    # 清理LLM返回的内容，移除markdown代码块标记
    cleaned_response = response.strip()
    if cleaned_response.startswith("```json"):
        cleaned_response = cleaned_response[7:]
    if cleaned_response.endswith("```"):
        cleaned_response = cleaned_response[:-3]
    cleaned_response = cleaned_response.strip()

    try:
        # 尝试直接解析为字典
        result_dict = json.loads(cleaned_response)
        if isinstance(result_dict, dict):
            return result_dict
    except json.JSONDecodeError:
        logging.warning("LLM返回的不是有效JSON，尝试解析为列表格式")
    
    try:
        # 尝试解析为原有的列表格式 [[图片标题...], [表格标题...]]
        response_list = json.loads(cleaned_response)
        if isinstance(response_list, list) and len(response_list) == 2:
            fig_captions, tab_captions = response_list
            result_dict = {}
            
            # 处理图片标题
            for i, caption in enumerate(fig_captions, 1):
                if caption.strip():
                    result_dict[f"fig_{i}"] = caption.strip()
            
            # 处理表格标题
            for i, caption in enumerate(tab_captions, 1):
                if caption.strip():
                    result_dict[f"tab_{i}"] = caption.strip()
            
            return result_dict
    except (json.JSONDecodeError, ValueError, IndexError) as e:
        logging.error(f"解析标题失败: {e}")
        logging.error(f"LLM返回内容: {response}")
        return {}


def add_context_to_image_explanations(image_explanations):
    """为图像解释添加上下文和过渡语句

    Args:
        image_explanations: 图像解释列表，每个元素包含detailed_explanation等字段

    Returns:
        list: 添加了context和transition的图像解释列表
    """
    import json

    if not image_explanations or len(image_explanations) == 0:
        return image_explanations

    # 将图像解释转换为文本格式供LLM处理
    explanations_text = json.dumps(image_explanations, ensure_ascii=False, indent=2)

    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    response = create_chat_completion(prompt, explanations_text)

    # 清理LLM返回的内容，移除markdown代码块标记
    cleaned_response = response.strip()
    if cleaned_response.startswith("```json"):
        cleaned_response = cleaned_response[7:]
    if cleaned_response.endswith("```"):
        cleaned_response = cleaned_response[:-3]
    cleaned_response = cleaned_response.strip()

    try:
        # 解析LLM返回的结果
        updated_explanations = json.loads(cleaned_response)
        if isinstance(updated_explanations, list) and len(updated_explanations) == len(image_explanations):
            logging.info("成功为图像解释添加上下文和过渡语句")
            return updated_explanations
        else:
            logging.warning("LLM返回结果格式不正确，保持原始解释")
            return image_explanations
    except json.JSONDecodeError as e:
        logging.error(f"解析LLM返回的JSON失败: {e}")
        logging.error(f"LLM返回内容: {response}")
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
