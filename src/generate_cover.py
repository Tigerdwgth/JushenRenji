import os
import logging
import requests
import time
import base64
import subprocess

from PIL import Image
from config import DASHSCOPE_API_KEY, GEMINI_API_KEY

logger = logging.getLogger(__name__)

# ---- Prompt 模板 ----
_COVER_PROMPT_TEMPLATE = (
    "一张可爱的卡通风格科技海报插画。"
    "论文主题：{title}。论文核心内容：{abstract}。"
    "请根据论文内容设计画面元素，用可爱卡通的方式表达论文的核心概念。"
    "画面中有一个可爱的圆润小机器人参与其中，大眼睛，表情萌趣。"
    "背景是柔和的渐变色，点缀与论文主题相关的科技装饰元素。"
    "整体风格：日系可爱漫画风、圆润线条、柔和配色、温暖明亮。"
    "高质量插画，16:9横版构图。"
    "画面中下方用醒目的中文艺术字写着「{title}」，字体风格可爱圆润，与整体画风统一。"
)


# Tailscale exit node (美国 LA) 用于访问 Google API
_TAILSCALE_EXIT_NODE = "100.103.134.38"


def _set_exit_node(node_ip: str = ""):
    """开启/关闭 Tailscale exit node。需要 root 权限或 sudo。"""
    cmd = ["sudo", "tailscale", "set", "--exit-node=" + node_ip]
    try:
        subprocess.run(cmd, timeout=10, check=True, capture_output=True)
        if node_ip:
            logger.info("Tailscale exit node 已开启: %s", node_ip)
        else:
            logger.info("Tailscale exit node 已关闭")
        return True
    except Exception as e:
        logger.warning("Tailscale exit node 设置失败: %s", e)
        return False


def _generate_cover_gemini(title: str, paper_abstract: str = "") -> str:
    """使用 Gemini 生成封面图片，自动通过 Tailscale exit node 访问 Google API。"""
    if not GEMINI_API_KEY:
        logger.warning("未配置 GEMINI_API_KEY，跳过 Gemini 生图")
        return ""

    abstract_short = (paper_abstract or "")[:300]
    prompt = _COVER_PROMPT_TEMPLATE.format(title=title, abstract=abstract_short)

    api_url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3-pro-image-preview:generateContent"
        "?key=" + GEMINI_API_KEY
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }

    # 开启 exit node 访问 Google API
    exit_node_enabled = _set_exit_node(_TAILSCALE_EXIT_NODE)
    try:
        resp = requests.post(
            api_url,
            json=payload,
            timeout=600,
        )
        resp.raise_for_status()
        data = resp.json()

        # 解析返回的图片
        candidates = data.get("candidates", [])
        for candidate in candidates:
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                inline_data = part.get("inlineData", {})
                if inline_data.get("mimeType", "").startswith("image/"):
                    img_bytes = base64.b64decode(inline_data["data"])
                    save_path = os.path.join("./cache", "gemini_cover.png")
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(img_bytes)
                    logger.info("Gemini 封面已生成: %s", save_path)
                    return save_path

        logger.warning("Gemini 返回中未找到图片: %s", str(data)[:500])
        return ""
    except Exception as e:
        logger.warning("Gemini 生图失败: %s", e)
        return ""
    finally:
        if exit_node_enabled:
            _set_exit_node("")


def _generate_cover_dashscope(title: str, paper_abstract: str = "") -> str:
    """回退方案：使用 DashScope qwen-image 生成封面。"""
    if not DASHSCOPE_API_KEY:
        return ""

    abstract_short = (paper_abstract or "")[:200]
    prompt = _COVER_PROMPT_TEMPLATE.format(title=title, abstract=abstract_short)

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + DASHSCOPE_API_KEY,
        "X-DashScope-Async": "enable",
    }
    payload = {
        "model": "qwen-image",
        "input": {"prompt": prompt},
        "parameters": {"size": "1280*720", "n": 1},
    }

    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("output", {}).get("task_id")
        if not task_id:
            return ""
        logger.info("DashScope 文生图任务已创建: %s", task_id)
    except Exception as e:
        logger.warning("DashScope 请求失败: %s", e)
        return ""

    query_url = "https://dashscope.aliyuncs.com/api/v1/tasks/" + task_id
    query_headers = {"Authorization": "Bearer " + DASHSCOPE_API_KEY}
    for _ in range(60):
        time.sleep(5)
        try:
            qr = requests.get(query_url, headers=query_headers, timeout=10)
            qr_data = qr.json()
            status = qr_data.get("output", {}).get("task_status", "")
            if status == "SUCCEEDED":
                results = qr_data.get("output", {}).get("results", [])
                if results:
                    image_url = results[0].get("url", "")
                    if image_url:
                        img_resp = requests.get(image_url, timeout=30)
                        save_path = os.path.join("./cache", "dashscope_cover.png")
                        os.makedirs(os.path.dirname(save_path), exist_ok=True)
                        with open(save_path, "wb") as f:
                            f.write(img_resp.content)
                        logger.info("DashScope 封面已下载: %s", save_path)
                        return save_path
                return ""
            elif status == "FAILED":
                logger.warning("DashScope 任务失败: %s", qr_data)
                return ""
        except Exception as e:
            logger.warning("DashScope 轮询失败: %s", e)
    return ""


def generate_cover(cover_pic, cover_title, output_path="./pic/cover.png", paper_abstract=""):
    """生成封面图片。优先 Gemini，回退 DashScope，再回退原始图片。

    标题直接由 AI 在画面中生成，不再程序叠加。
    """
    try:
        # 优先使用 Gemini
        bg_path = _generate_cover_gemini(cover_title, paper_abstract=paper_abstract)

        # 回退 DashScope
        if not bg_path or not os.path.exists(bg_path):
            logger.info("Gemini 不可用，回退到 DashScope")
            bg_path = _generate_cover_dashscope(cover_title, paper_abstract=paper_abstract)

        # 最终回退
        if bg_path and os.path.exists(bg_path):
            background = Image.open(bg_path).convert("RGB")
            logger.info("使用 AI 生成的封面")
        else:
            background = Image.open(cover_pic).convert("RGB")
            logger.info("AI 封面不可用，使用原始图片")

        # 统一尺寸 1280x720
        background = background.resize((1280, 720), Image.Resampling.LANCZOS)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        background.save(output_path, quality=95)
        logger.info("封面已保存: %s", output_path)
    except Exception as e:
        logger.error("封面生成失败: %s", e)
        raise e


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    cover_pic = "./pic/1.png"
    cover_title = "像素级联合嵌入预测架构"
    abstract = (
        "LeWorldModel提出首个从原始像素端到端稳定训练的联合嵌入预测架构JEPA，"
        "仅用MSE预测损失和SIGReg正则化两个损失项，解决了表示坍缩问题。"
        "在Push-T等机器人操控任务上比PLDM高出18%成功率，规划速度比基础模型方法快48倍。"
    )
    output_path = "./output/cover_test.png"
    generate_cover(cover_pic, cover_title, output_path, paper_abstract=abstract)
