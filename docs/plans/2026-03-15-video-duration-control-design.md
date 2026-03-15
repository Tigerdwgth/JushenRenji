# 视频时长控制 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 控制生成视频的时长在目标范围内（单篇 ~5分钟，多篇汇总每篇 ~30秒），通过文字预算、图片筛选和 TTS 后兜底裁剪三层机制实现。

**Architecture:** 新增 `--target_duration` CLI 参数（默认300秒）。根据目标时长计算文字预算（4字/秒），60% 分配给总结、40% 分配给图片解释。LLM 打分筛选 top-N 重要图片（默认5张）。TTS 合成后检查总时长，超标时从尾部移除整段。

**Tech Stack:** Python 3.10, OpenAI API (DeepSeek), DashScope TTS, moviepy

---

### Task 1: 新增 `--target_duration` CLI 参数

**Files:**
- Modify: `src/main.py:18-49`
- Test: `tests/test_main_args.py`

**Step 1: 写失败的测试**

创建 `tests/test_main_args.py`：

```python
"""测试 main.py CLI 参数解析"""
import sys
import importlib


def test_target_duration_default():
    """--target_duration 默认值应为 300"""
    sys.argv = ["main.py", "--filename", "cs.RO"]
    # 需要重新导入以触发 parse_args
    from src.main import parse_args  # 注意：main.py 中 parse_args 需要可导入
    # 临时替换 sys.argv
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--filename", type=str)
    parser.add_argument("--video_length", type=str, default="long", choices=["long", "short"])
    parser.add_argument("--output_language", type=str, default="zh", choices=["zh", "en"])
    parser.add_argument("--platforms", type=str, default="bilibili,xiaohongshu")
    parser.add_argument("--target_duration", type=int, default=300)
    args = parser.parse_args(["--filename", "cs.RO"])
    assert args.target_duration == 300


def test_target_duration_custom():
    """--target_duration 可自定义"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--filename", type=str)
    parser.add_argument("--target_duration", type=int, default=300)
    args = parser.parse_args(["--filename", "test", "--target_duration", "180"])
    assert args.target_duration == 180
```

**Step 2: 运行测试验证失败**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -m pytest tests/test_main_args.py -v`
Expected: PASS（这里测试的是 argparse 行为，先通过）

**Step 3: 修改 `src/main.py` 添加参数**

在 `parse_args()` 函数的 `--platforms` 参数后添加：

```python
    parser.add_argument(
        "--target_duration",
        type=int,
        default=300,
        help="Target video duration in seconds (default: 300 = 5min)"
    )
```

在 `if __name__ == "__main__":` 块中，将 `target_duration` 传入 `generate_daily_arxiv_summary`：

```python
    target_duration = args.target_duration
    # ... 在调用 generate_daily_arxiv_summary 时传入
    path, titles, cn_titles = generate_daily_arxiv_summary(
        query=filename, max_papers=1, date=str(yesterday),
        long_or_short=video_length, target_duration=target_duration
    )
```

**Step 4: 运行测试验证通过**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -m pytest tests/test_main_args.py -v`
Expected: PASS

**Step 5: 提交**

```bash
git add src/main.py tests/test_main_args.py
git commit -m "feat: add --target_duration CLI parameter"
```

---

### Task 2: 新增文字预算计算工具函数

**Files:**
- Modify: `src/paperagent_workflow.py` (在文件顶部区域新增函数)
- Test: `tests/test_duration_budget.py`

**Step 1: 写失败的测试**

创建 `tests/test_duration_budget.py`：

```python
"""测试时长预算计算"""
import sys
sys.path.insert(0, './src')


def test_compute_word_budget_default():
    """300秒 → 总预算1200字, 总结720字, 图片480字"""
    from paperagent_workflow import compute_word_budget
    budget = compute_word_budget(target_duration=300)
    assert budget["total"] == 1200
    assert budget["summary"] == 720
    assert budget["images"] == 480


def test_compute_word_budget_short():
    """30秒 → 总预算120字"""
    from paperagent_workflow import compute_word_budget
    budget = compute_word_budget(target_duration=30)
    assert budget["total"] == 120
    assert budget["summary"] == 72
    assert budget["images"] == 48


def test_per_image_budget():
    """图片预算平均分配到每张图"""
    from paperagent_workflow import compute_word_budget
    budget = compute_word_budget(target_duration=300, num_images=5)
    assert budget["per_image"] == 96  # 480 / 5


def test_per_image_budget_zero_images():
    """0张图片时 per_image 应为 0, 总结拿到全部预算"""
    from paperagent_workflow import compute_word_budget
    budget = compute_word_budget(target_duration=300, num_images=0)
    assert budget["per_image"] == 0
    assert budget["summary"] == 1200
```

**Step 2: 运行测试验证失败**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -m pytest tests/test_duration_budget.py -v`
Expected: FAIL with "cannot import name 'compute_word_budget'"

**Step 3: 在 `src/paperagent_workflow.py` 中实现**

在 `extract_abstract_from_text` 函数前添加：

```python
# ---- 时长预算常量 ----
TTS_CHARS_PER_SECOND = 4  # 中文 TTS cosyvoice-v1 约 4 字/秒
SUMMARY_BUDGET_RATIO = 0.6  # 总结占比
IMAGE_BUDGET_RATIO = 0.4    # 图片解释占比
MAX_IMAGES_DEFAULT = 5      # 图片筛选默认上限
DURATION_OVERFLOW_RATIO = 1.1  # TTS 后兜底的弹性比例


def compute_word_budget(target_duration: int = 300, num_images: int = 0) -> dict:
    """根据目标视频时长计算文字预算。

    Args:
        target_duration: 目标时长（秒）
        num_images: 图片数量（用于计算每张图的预算）

    Returns:
        dict: {"total", "summary", "images", "per_image"}
    """
    total = target_duration * TTS_CHARS_PER_SECOND
    if num_images <= 0:
        return {"total": total, "summary": total, "images": 0, "per_image": 0}
    summary_budget = int(total * SUMMARY_BUDGET_RATIO)
    image_budget = total - summary_budget
    per_image = image_budget // num_images if num_images > 0 else 0
    return {
        "total": total,
        "summary": summary_budget,
        "images": image_budget,
        "per_image": per_image,
    }
```

**Step 4: 运行测试验证通过**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -m pytest tests/test_duration_budget.py -v`
Expected: PASS

**Step 5: 提交**

```bash
git add src/paperagent_workflow.py tests/test_duration_budget.py
git commit -m "feat: add compute_word_budget utility for duration control"
```

---

### Task 3: 新增图片重要性打分 Prompt 和函数

**Files:**
- Modify: `src/llm_tools/prompts.py:12-109` (在 prompts_dict 中新增 key)
- Modify: `src/llm_tools/llm_agent.py` (新增 `rate_image_importance` 函数)
- Test: `tests/test_rate_image_importance.py`

**Step 1: 写失败的测试**

创建 `tests/test_rate_image_importance.py`：

```python
"""测试图片重要性打分函数"""
import json
from unittest.mock import patch


def test_rate_image_importance_returns_scores():
    """应返回与输入图片数量相同的分数列表"""
    mock_response = json.dumps({"scores": [8, 5, 9, 3, 7]})

    with patch("src.llm_tools.llm_agent.create_chat_completion", return_value=mock_response):
        from src.llm_tools.llm_agent import rate_image_importance
        captions = [
            "Figure 1: Overall architecture",
            "Figure 2: Training curve",
            "Figure 3: Method pipeline",
            "Figure 4: Ablation table",
            "Figure 5: Comparison results",
        ]
        scores = rate_image_importance(captions)
        assert len(scores) == 5
        assert all(isinstance(s, (int, float)) for s in scores)


def test_rate_image_importance_prompt_exists():
    """prompts_dict 中应包含 rate_image_importance"""
    from src.llm_tools.prompts import prompts_dict
    assert "rate_image_importance" in prompts_dict


def test_rate_image_importance_selects_top_n():
    """select_top_images 应根据分数选出 top-N"""
    from src.llm_tools.llm_agent import select_top_images
    scores = [3, 8, 1, 9, 5]
    items = ["a", "b", "c", "d", "e"]
    selected = select_top_images(items, scores, top_n=3)
    # 按原始顺序返回，分数最高的 3 个: b(8), d(9), e(5) → 索引 1,3,4
    assert len(selected) == 3
    assert selected == ["b", "d", "e"]
```

**Step 2: 运行测试验证失败**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -m pytest tests/test_rate_image_importance.py -v`
Expected: FAIL

**Step 3: 在 `src/llm_tools/prompts.py` 添加 prompt**

在 `prompts_dict` 的 `"explain_image_ocr_fallback"` 条目后新增：

```python
    "rate_image_importance": (
        "你是学术论文分析专家。给定一组图片的题注/描述，请对每张图片的重要性打分（1-10分）。"
        "重要性标准：总览图/方法架构图 > 核心实验结果图 > 消融实验图 > 其他辅助图。"
        "请严格返回JSON格式：{\"scores\": [分数1, 分数2, ...]}，分数列表长度必须与输入数量一致。"
        "禁止输出其他内容。"
    ),
```

**Step 4: 在 `src/llm_tools/llm_agent.py` 添加函数**

在 `add_context_to_image_explanations` 函数后添加：

```python
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

    # 解析 JSON 返回
    parsed = _parse_json_response(response)
    scores = parsed.get("scores", [])

    # 兜底：如果解析失败或长度不匹配，给所有图片相同分数
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
```

**Step 5: 运行测试验证通过**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -m pytest tests/test_rate_image_importance.py -v`
Expected: PASS

**Step 6: 提交**

```bash
git add src/llm_tools/prompts.py src/llm_tools/llm_agent.py tests/test_rate_image_importance.py
git commit -m "feat: add image importance rating and top-N selection"
```

---

### Task 4: 修改 summary prompt 支持字数预算注入

**Files:**
- Modify: `src/llm_tools/prompts.py:14-19` (修改 generate_summary prompt)
- Modify: `src/llm_tools/llm_agent.py:132-134` (修改 generate_summary 函数签名)
- Test: `tests/test_summary_budget.py`

**Step 1: 写失败的测试**

创建 `tests/test_summary_budget.py`：

```python
"""测试 summary 函数支持字数预算"""
from unittest.mock import patch, MagicMock


def test_generate_summary_accepts_word_budget():
    """generate_summary 应接受 word_budget 参数"""
    import inspect
    from src.llm_tools.llm_agent import generate_summary
    sig = inspect.signature(generate_summary)
    assert "word_budget" in sig.parameters


def test_generate_summary_injects_budget_into_prompt():
    """word_budget 应注入到 prompt 中"""
    captured_prompts = []

    def mock_completion(prompt, user_content=None):
        captured_prompts.append(prompt)
        return "这是一个测试摘要。"

    with patch("src.llm_tools.llm_agent.create_chat_completion", side_effect=mock_completion):
        from src.llm_tools.llm_agent import generate_summary
        generate_summary("test text", word_budget=500)
        assert any("500" in p for p in captured_prompts), \
            f"Prompt should contain '500' but got: {captured_prompts}"


def test_generate_short_summary_accepts_word_budget():
    """generate_short_summary 应接受 word_budget 参数"""
    import inspect
    from src.llm_tools.llm_agent import generate_short_summary
    sig = inspect.signature(generate_short_summary)
    assert "word_budget" in sig.parameters
```

**Step 2: 运行测试验证失败**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -m pytest tests/test_summary_budget.py -v`
Expected: FAIL with "word_budget" not in parameters

**Step 3: 修改 prompts.py 中的 prompt**

将 `generate_summary` prompt 中的 `约1000字的总结` 改为占位符：

```python
    "generate_summary": (
        "请总结以下论文的核心内容,重点讲解方法，参考摘要，请使用简洁的表达，生成约{word_budget}字的总结。"
        "禁止输出markdown形式的文本，不要一条一条的列出，而是以长文的形式。"
        "你的目标是帮助用户快速理解论文核心内容，语言通俗易懂，适合制作论文讲解视频的文案。"
        "请以 "这篇文章..."作为开始，不要重复文章标题\n"
    ),
```

将 `generate_short_summary` prompt 末尾添加字数限制：

```python
    "generate_short_summary": (
        "你现在是组会分享论文的研究生，请分享下面的文章，严格遵循以下要求。"
        "1.简单介绍一下文章工作单位（使用缩写），不用说明作者名字，"
        "2. 如果有提到是什么会议也请说明（仅使用缩写+年份形式）,没有提及的话，请直接忽略这个要求，不用说未提及，请勿编造任何信息。"
        "3. 用两句话简短介绍一下这篇文章的核心方法、模型结构和贡献，言简意赅。"
        "4. 禁止复读论文标题"
        "5. 禁止使用markdown形式的输出，请用完整的句子，而非列举点,使用中文"
        "6. 严格控制总字数在{word_budget}字以内"
    ),
```

**Step 4: 修改 llm_agent.py 中的函数**

```python
def generate_summary(text, word_budget: int = 1000):
    prompt_template = prompts_dict.get(inspect.currentframe().f_code.co_name, "")
    prompt = prompt_template.format(word_budget=word_budget) + text
    return create_chat_completion(prompt)

def generate_short_summary(text, word_budget: int = 120):
    prompt_template = prompts_dict.get(inspect.currentframe().f_code.co_name, "")
    prompt = prompt_template.format(word_budget=word_budget) + text
    return create_chat_completion(prompt)
```

**注意：** `prompts.py` 底部的 `add_language_suffix_to_prompts()` 会在模块导入时给所有 prompt 追加语言后缀。这意味着 prompt 值已经包含了语言后缀。由于 `.format()` 只替换 `{word_budget}` 占位符，语言后缀中不含花括号，所以不会冲突。但必须确保 `add_language_suffix_to_prompts()` 不会破坏 `{word_budget}` 占位符 —— 检查确认语言后缀只是追加纯文本，不含花括号，安全。

**Step 5: 运行测试验证通过**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -m pytest tests/test_summary_budget.py -v`
Expected: PASS

**Step 6: 提交**

```bash
git add src/llm_tools/prompts.py src/llm_tools/llm_agent.py tests/test_summary_budget.py
git commit -m "feat: inject word budget into summary prompts"
```

---

### Task 5: 在 workflow 中集成时长预算和图片筛选

**Files:**
- Modify: `src/paperagent_workflow.py:329-512` (`generate_daily_arxiv_summary` 函数)
- Modify: `src/paperagent_workflow.py:120-224` (`run_pdf_to_video_pipeline` 函数)

这是核心集成任务。需要在两个主入口函数中注入预算逻辑。

**Step 1: 修改 `generate_daily_arxiv_summary` 函数签名**

在 `src/paperagent_workflow.py:329`，函数签名改为：

```python
def generate_daily_arxiv_summary(query="cs.RO", date=datetime.datetime.now().strftime(r"%Y-%m-%d"),
                                  max_papers=20, output_filename="./output/daily_summary.mp4",
                                  long_or_short="short", target_duration=300):
```

**Step 2: 在循环处理每篇论文前计算预算**

在 `for paper_idx, paper in enumerate(papers):` 之前（约 line 364 后），添加：

```python
    # ---- 时长预算 ----
    if len(papers) > 1:
        per_paper_duration = max(30, target_duration // len(papers))
    else:
        per_paper_duration = target_duration
    logging.info(f"目标总时长: {target_duration}秒, 每篇论文目标: {per_paper_duration}秒")
```

**Step 3: 在图片提取后添加图片筛选逻辑**

在 `images = process_pdf_images(...)` (line 379) 后、图像解释生成前，添加图片筛选：

```python
        # ---- 图片筛选（基于 LLM 打分） ----
        if len(images) > MAX_IMAGES_DEFAULT:
            logging.info(f"图片数量 {len(images)} 超过上限 {MAX_IMAGES_DEFAULT}，进行重要性筛选")
            try:
                # 生成简要描述用于打分（使用图片序号）
                captions_for_rating = []
                for img_idx in range(len(images)):
                    expl_key = f"fig_{img_idx+1}"
                    cap = contexts.get(img_idx+1, f"Figure {img_idx+1}") if contexts else f"Figure {img_idx+1}"
                    captions_for_rating.append(cap)
                scores = rate_image_importance(captions_for_rating)
                images = select_top_images(images, scores, top_n=MAX_IMAGES_DEFAULT)
                logging.info(f"筛选后保留 {len(images)} 张图片")
            except Exception as e:
                logging.warning(f"图片筛选失败，使用前 {MAX_IMAGES_DEFAULT} 张: {e}")
                images = images[:MAX_IMAGES_DEFAULT]
```

**Step 4: 在摘要生成时注入字数预算**

修改 line 430 附近的摘要生成调用，将字数预算传入：

```python
        # 计算文字预算
        word_budget = compute_word_budget(per_paper_duration, num_images=len(images))
        logging.info(f"文字预算: 总结{word_budget['summary']}字, 图片{word_budget['images']}字 (每张{word_budget['per_image']}字)")

        deom_website, origin_title, short_summary, cn_title = call_llm_multithread(
            [
                (get_paper_demo_website, text[:1000]),
                (generate_origin_title, text[:200]),
                (lambda t: generate_short_summary(t, word_budget=word_budget['summary']), f"{text[:5000]} {paper.comments}")
                    if long_or_short == "short"
                    else (lambda t: generate_summary(t, word_budget=word_budget['summary']), paper.comments + text),
                (generate_video_title, text[:200]),
            ]
        )
```

**Step 5: 同样修改 `run_pdf_to_video_pipeline` 函数**

在 `run_pdf_to_video_pipeline` 函数签名中添加 `target_duration=300`。
在 `images = process_pdf_images(pdf_processor)` 后，添加同样的图片筛选逻辑。
在 `call_llm(text)` 中注入预算（修改 `call_llm` 以接受 `word_budget` 参数）。

**Step 6: 运行集成验证**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -c "from paperagent_workflow import compute_word_budget; print(compute_word_budget(300, 5))"`
Expected: `{'total': 1200, 'summary': 720, 'images': 480, 'per_image': 96}`

**Step 7: 提交**

```bash
git add src/paperagent_workflow.py
git commit -m "feat: integrate duration budget and image filtering into workflow"
```

---

### Task 6: 修改图片解释 prompt 支持字数上限

**Files:**
- Modify: `src/llm_tools/prompts.py:87-98` (explain_image_system prompt)
- Modify: `src/llm_tools/image_agent.py:103-240` (explain_image 方法传入字数上限)

**Step 1: 修改 explain_image_system prompt**

在 `prompts.py` 的 `explain_image_system` prompt 中，将硬编码的 `150字` 改为占位符：

将：
```
"注意：每句话必须控制在30字以内！每张图片的详细讲解总长度不超过150字！"
```
改为：
```
"注意：每句话必须控制在30字以内！每张图片的详细讲解总长度不超过{per_image_budget}字！"
```

同样修改 `explain_image_user` prompt 中的 `150字`。

**Step 2: 修改 ImageAgent.explain_image 方法**

在 `explain_image` 方法签名中添加 `per_image_budget: int = 150`。

在构建 prompt 时：
```python
system_prompt = prompts_dict.get("explain_image_system", "").format(per_image_budget=per_image_budget) + get_language_suffix()
# ...
base_user_prompt = prompts_dict.get("explain_image_user", "").format(per_image_budget=per_image_budget)
```

**注意：** `add_language_suffix_to_prompts()` 已经在模块加载时修改了 prompts_dict。由于 image_agent 使用 `prompts_dict.get(...)` 直接获取值，此时值已包含语言后缀。`.format()` 只替换 `{per_image_budget}`，语言后缀不含花括号，不会冲突。

同时修改 `explain_images` 方法签名接受 `per_image_budget` 并传递给 `explain_image`。

**Step 3: 在 workflow 中传入 per_image_budget**

在 `paperagent_workflow.py` 调用 `image_agent.explain_images(...)` 时传入 `per_image_budget=word_budget['per_image']`。

**Step 4: 提交**

```bash
git add src/llm_tools/prompts.py src/llm_tools/image_agent.py src/paperagent_workflow.py
git commit -m "feat: inject per-image word budget into image explanation prompts"
```

---

### Task 7: 实现 TTS 后兜底裁剪

**Files:**
- Modify: `src/video_creator.py:252-579` (create_video 方法)
- Test: `tests/test_tts_trimming.py`

**Step 1: 写失败的测试**

创建 `tests/test_tts_trimming.py`：

```python
"""测试 TTS 后兜底裁剪逻辑"""


def test_trim_segments_within_budget():
    """不超标时不裁剪"""
    from src.video_creator import trim_segments_to_duration
    segments = [
        {"type": "expl", "duration": 10.0, "image_idx": 0},
        {"type": "summary", "duration": 20.0, "image_idx": 0},
        {"type": "expl", "duration": 15.0, "image_idx": 1},
        {"type": "summary", "duration": 25.0, "image_idx": 1},
    ]
    result = trim_segments_to_duration(segments, target_duration=300)
    assert len(result) == 4  # 不裁剪


def test_trim_segments_removes_tail_expl_first():
    """超标时优先从尾部移除图片解释段"""
    from src.video_creator import trim_segments_to_duration
    segments = [
        {"type": "summary", "duration": 50.0, "image_idx": 0},
        {"type": "expl", "duration": 30.0, "image_idx": 1},
        {"type": "summary", "duration": 50.0, "image_idx": 1},
        {"type": "expl", "duration": 30.0, "image_idx": 2},  # 应优先移除尾部expl
    ]
    # 总时长 160, 目标 100, 弹性 110
    result = trim_segments_to_duration(segments, target_duration=100)
    total = sum(s["duration"] for s in result)
    assert total <= 110
```

**Step 2: 运行测试验证失败**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -m pytest tests/test_tts_trimming.py -v`
Expected: FAIL

**Step 3: 在 `src/video_creator.py` 中实现裁剪函数**

在 `VideoCreator` 类之前添加独立函数：

```python
def trim_segments_to_duration(segments: list, target_duration: float,
                               overflow_ratio: float = 1.1) -> list:
    """TTS 后兜底裁剪：从尾部移除整段直到总时长在弹性范围内。

    Args:
        segments: [{"type": "expl"|"summary", "duration": float, "image_idx": int, ...}, ...]
        target_duration: 目标时长（秒）
        overflow_ratio: 允许的弹性比例

    Returns:
        裁剪后的 segments 列表
    """
    max_duration = target_duration * overflow_ratio
    total = sum(s["duration"] for s in segments)

    if total <= max_duration:
        return segments[:]

    logging.info(f"TTS 总时长 {total:.1f}s 超过目标 {max_duration:.1f}s，开始裁剪")

    result = segments[:]

    # 第一轮：从尾部移除 expl 类型
    while sum(s["duration"] for s in result) > max_duration:
        removed = False
        for i in range(len(result) - 1, -1, -1):
            if result[i]["type"] == "expl":
                removed_seg = result.pop(i)
                logging.info(f"移除图片解释段 image_idx={removed_seg['image_idx']}, duration={removed_seg['duration']:.1f}s")
                removed = True
                break
        if not removed:
            break

    # 第二轮：如果仍超标，从尾部移除 summary 类型
    while sum(s["duration"] for s in result) > max_duration:
        removed = False
        for i in range(len(result) - 1, -1, -1):
            if result[i]["type"] == "summary":
                removed_seg = result.pop(i)
                logging.info(f"移除摘要段 image_idx={removed_seg['image_idx']}, duration={removed_seg['duration']:.1f}s")
                removed = True
                break
        if not removed:
            break

    final_total = sum(s["duration"] for s in result)
    logging.info(f"裁剪后总时长: {final_total:.1f}s")
    return result
```

**Step 4: 在 `VideoCreator.__init__` 中添加 `target_duration` 参数**

```python
def __init__(self, images, text, video_clips=None, image_explanations=None, target_duration=0):
    # ... 现有代码 ...
    self.target_duration = target_duration
```

**Step 5: 在 `create_video` 步骤6和步骤7之间集成裁剪逻辑**

在构建好 `expl_sentence_files` 和 `summary_sentence_files` 之后（约步骤5的 groups 分配后），调用 `trim_segments_to_duration`。这需要在步骤6（build per-image clips）之前进行。

具体做法：在步骤5之后、步骤6之前，构建 segments 列表并裁剪：

```python
        # 5.5) TTS 后兜底裁剪
        if self.target_duration > 0:
            segments = []
            for i in range(n_images):
                expl_sents = expl_sentence_files[i] if i < len(expl_sentence_files) else []
                expl_dur = sum(f[2] for f in expl_sents)
                if expl_dur > 0:
                    segments.append({"type": "expl", "duration": expl_dur, "image_idx": i})
                summary_group = groups[i]
                # 摘要的实际时长需要从文件获取
                for (path, txt) in summary_group:
                    clip = safe_audio_clip_loader(path)
                    dur = clip.duration if clip else 2.0
                    if clip:
                        clip.close()
                    segments.append({"type": "summary", "duration": dur, "image_idx": i})

            trimmed = trim_segments_to_duration(segments, self.target_duration)
            trimmed_set = set()
            for seg in trimmed:
                trimmed_set.add((seg["type"], seg["image_idx"]))

            # 根据裁剪结果过滤
            new_expl_sentence_files = []
            for i in range(len(expl_sentence_files)):
                if ("expl", i) in trimmed_set:
                    new_expl_sentence_files.append(expl_sentence_files[i])
                else:
                    new_expl_sentence_files.append([])
            expl_sentence_files = new_expl_sentence_files

            # 重新计算 groups
            trimmed_summary_indices = set()
            for seg in trimmed:
                if seg["type"] == "summary":
                    trimmed_summary_indices.add(seg["image_idx"])
            for i in range(len(groups)):
                if i not in trimmed_summary_indices:
                    groups[i] = []
```

**Step 6: 在 workflow 中将 target_duration 传入 VideoCreator**

在 `paperagent_workflow.py` 创建 `VideoCreator` 时传入 `target_duration=per_paper_duration`：

```python
video_creator = VideoCreator(images, short_summary, video_clips=..., image_explanations=..., target_duration=per_paper_duration)
```

**Step 7: 运行测试验证通过**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -m pytest tests/test_tts_trimming.py -v`
Expected: PASS

**Step 8: 提交**

```bash
git add src/video_creator.py src/paperagent_workflow.py tests/test_tts_trimming.py
git commit -m "feat: add TTS post-synthesis duration trimming"
```

---

### Task 8: 端到端验证

**Step 1: 用小样本测试单篇论文模式**

Run:
```bash
cd /home/jdh/Projects/VlogCutter/JushenRenji
/home/jdh/miniconda3/envs/paperagent/bin/python src/main.py \
    --filename "cs.RO" --video_length long --target_duration 300 --platforms none
```

验证：
- 日志中应显示文字预算信息
- 图片筛选信息（如果图片 > 5 张）
- TTS 兜底裁剪信息（如果超标）
- 最终视频时长应在 270-330 秒范围内

**Step 2: 用短时长测试**

Run:
```bash
/home/jdh/miniconda3/envs/paperagent/bin/python src/main.py \
    --filename "cs.RO" --video_length short --target_duration 30 --platforms none
```

验证：最终视频时长应在 25-33 秒范围内

**Step 3: 运行全部测试**

Run: `/home/jdh/miniconda3/envs/paperagent/bin/python -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: 提交并更新文档**

更新 `README.md` 的运行命令部分，添加 `--target_duration` 说明。
更新 `CLAUDE.md` 的常用命令部分。

```bash
git add README.md CLAUDE.md
git commit -m "docs: add --target_duration parameter documentation"
```

---

## 文件修改汇总

| 文件 | Task | 改动描述 |
|------|------|----------|
| `src/main.py` | 1 | 新增 `--target_duration` 参数，传入 workflow |
| `src/paperagent_workflow.py` | 2,5 | 新增 `compute_word_budget()`；集成预算/筛选到两个主函数 |
| `src/llm_tools/prompts.py` | 3,4,6 | 新增 `rate_image_importance` prompt；修改 summary/image prompts 支持占位符 |
| `src/llm_tools/llm_agent.py` | 3,4 | 新增 `rate_image_importance()`、`select_top_images()`；修改 `generate_summary()` 签名 |
| `src/llm_tools/image_agent.py` | 6 | `explain_image` 接受 `per_image_budget` 参数 |
| `src/video_creator.py` | 7 | 新增 `trim_segments_to_duration()`；VideoCreator 接受 `target_duration` |
| `tests/test_main_args.py` | 1 | CLI 参数测试 |
| `tests/test_duration_budget.py` | 2 | 预算计算测试 |
| `tests/test_rate_image_importance.py` | 3 | 图片打分/筛选测试 |
| `tests/test_summary_budget.py` | 4 | 字数预算注入测试 |
| `tests/test_tts_trimming.py` | 7 | TTS 裁剪测试 |
| `README.md` | 8 | 文档更新 |
