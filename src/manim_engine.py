"""Manim 演示视频生成引擎。

从现有流水线的 structured_plan 和论文原文中提取公式、模型架构等内容，
由 LLM 自动生成 ManimCE 代码并渲染为动画视频。

固定 4 场景结构:
  Scene 1: TitleScene    -> opening script -> 标题动画
  Scene 2: IntroScene    -> intro script   -> 背景动画
  Scene 3: MethodScene   -> method script  -> 架构/公式动画
  Scene 4: ResultsScene  -> results script -> 结果表格动画
"""

import os
import json
import re
import subprocess
import logging
import glob
import time as _time
import yaml

from moviepy import VideoFileClip, concatenate_videoclips, AudioFileClip

from src.llm_tools.prompts import prompts_dict

logger = logging.getLogger(__name__)

# 渲染质量映射
QUALITY_MAP = {
    "low": "-ql",       # 480p
    "medium": "-qm",    # 720p
    "high": "-qh",      # 1080p
}

# 布局常量
TEXT_WRAP_THRESHOLD = 25      # 文本超过此字符数自动换行
MAX_FRAME_WIDTH = 12          # 画框最大宽度（安全区域）
MAX_FRAME_HEIGHT = 7          # 画框最大高度
SAFE_FRAME_WIDTH = 11         # 缩放目标宽度
SAFE_FRAME_HEIGHT = 6.5       # 缩放目标高度



def _load_manim_references():
    """加载 manim_skill 参考示例作为 few-shot 上下文。"""
    ref_dir = os.path.join(os.path.dirname(__file__), "manim_references")
    refs = []
    if os.path.isdir(ref_dir):
        for fname in sorted(os.listdir(ref_dir)):
            fpath = os.path.join(ref_dir, fname)
            if os.path.isfile(fpath):
                with open(fpath, "r", encoding="utf-8") as f:
                    refs.append(f"### {fname}\n{f.read()}")
    return "\n\n".join(refs) if refs else ""


_manim_references_cache = None

def _get_manim_references():
    global _manim_references_cache
    if _manim_references_cache is None:
        _manim_references_cache = _load_manim_references()
        logger.info("加载了 manim_skill 参考示例 (%d 字符)", len(_manim_references_cache))
    return _manim_references_cache


def _init_manim_llm():
    """初始化 Manim 专用的 LLM 客户端（DeepSeek-R1 via DeepSeek API）。"""
    from openai import OpenAI

    config_path = "config.yaml"
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    api_key = config.get("llm_api_key") or os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise ValueError("llm_api_key 未配置")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com/v1",
    )
    return client, "deepseek-reasoner"


# 延迟初始化
_manim_client = None
_manim_model = None


def manim_chat(prompt, user_content=None, max_retries=3):
    """Manim 专用 LLM 调用（DeepSeek-R1 + manim_skill 参考示例）。"""
    global _manim_client, _manim_model
    if _manim_client is None:
        _manim_client, _manim_model = _init_manim_llm()
        logger.info("Manim LLM 客户端初始化完成: model=%s", _manim_model)

    # 注入 manim_skill 参考示例
    refs = _get_manim_references()
    if refs:
        prompt = prompt + "\n\n## ManimCE 参考示例和最佳实践（请严格参考这些代码风格）\n" + refs[:8000]

    messages = [{"role": "user", "content": prompt + ("\n\n" + user_content if user_content else "")}]

    for attempt in range(max_retries):
        try:
            response = _manim_client.chat.completions.create(
                model=_manim_model,
                messages=messages,
            )
            return response.choices[0].message.content
        except Exception as e:
            wait = 2 ** attempt
            logger.warning("Manim LLM 调用失败 (第%d次), %ds 后重试: %s", attempt + 1, wait, e)
            if attempt < max_retries - 1:
                _time.sleep(wait)
            else:
                raise


class ManimEngine:
    """Manim 动画生成引擎（固定 4 场景结构）。"""

    def __init__(self, paper_text, structured_plan=None, output_dir="./output/manim"):
        self.paper_text = paper_text
        self.structured_plan = structured_plan or {}
        self.output_dir = output_dir
        self.temp_dir = os.path.join(output_dir, "temp")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        self._config_cache = None

    # ------------------------------------------------------------------
    # 代码安全: 注入边界检查
    # ------------------------------------------------------------------

    def _wrap_long_texts(self, code):
        """自动给长 Text 字符串插入换行，支持 CJK 字符。"""
        def _has_cjk(text):
            return any('\u4e00' <= c <= '\u9fff' for c in text)

        def _wrap_long_text(match):
            full = match.group(0)
            text_match = re.search(r'Text\(\s*["\'](.*?)["\']', full, re.DOTALL)
            if not text_match:
                return full
            text = text_match.group(1)
            if "\\n" in text or "\n" in text or len(text) <= TEXT_WRAP_THRESHOLD:
                return full
            threshold = TEXT_WRAP_THRESHOLD
            if _has_cjk(text):
                lines = [text[i:i+threshold] for i in range(0, len(text), threshold)]
            else:
                words = text.split(" ")
                lines = []
                current = ""
                for w in words:
                    if current and len(current) + 1 + len(w) > threshold:
                        lines.append(current)
                        current = w
                    else:
                        current = (current + " " + w).strip()
                if current:
                    lines.append(current)
            new_text = "\\n".join(lines)
            return full.replace(text, new_text)

        pattern = r'Text\(\s*["\'][^"\']{' + str(TEXT_WRAP_THRESHOLD) + r',}["\'][^)]*\)'
        code = re.sub(pattern, _wrap_long_text, code)
        return code

    def _remove_trailing_fadeout(self, code):
        """移除末尾的 FadeOut，替换为 wait（防止最后一帧变黑）。"""
        lines = code.split('\n')
        for i in range(len(lines) - 1, -1, -1):
            if 'FadeOut' in lines[i] and 'self.play' in lines[i]:
                indent = len(lines[i]) - len(lines[i].lstrip())
                lines[i] = ' ' * indent + 'self.wait(2)  # 保持内容显示'
                break
        return '\n'.join(lines)

    def _inject_scale_safety(self, code):
        """注入 VGroup 缩放安全网，防止内容超出画框。"""
        lines = code.split('\n')
        safety = [
            '        # === Auto-scale safety net ===',
            '        _all_mobs = VGroup(*[m for m in self.mobjects if isinstance(m, VMobject)])',
            '        if len(_all_mobs) > 0:',
            '            if _all_mobs.width > ' + str(MAX_FRAME_WIDTH) + ':',
            '                _all_mobs.scale_to_fit_width(' + str(SAFE_FRAME_WIDTH) + ')',
            '            if _all_mobs.height > ' + str(MAX_FRAME_HEIGHT) + ':',
            '                _all_mobs.scale_to_fit_height(' + str(SAFE_FRAME_HEIGHT) + ')',
        ]
        insert_idx = len(lines) - 1
        for i in range(len(lines) - 1, -1, -1):
            stripped = lines[i].strip()
            if stripped and not stripped.startswith('#'):
                insert_idx = i
                break
        lines = lines[:insert_idx] + safety + lines[insert_idx:]
        return '\n'.join(lines)

    def inject_bounds_check(self, code):
        """注入自动缩放安全网、移除末尾 FadeOut、自动给长文本换行。"""
        code = self._wrap_long_texts(code)
        code = self._remove_trailing_fadeout(code)
        code = self._inject_scale_safety(code)
        return code


    def _opencode_generate(self, prompt_text):
        """通过 opencode headless 模式调用 DeepSeek-R1 生成代码。
        opencode 会自动加载 manim_skill 最佳实践。"""


        # 写 prompt 到临时文件避免 shell 转义问题
        prompt_file = os.path.join(self.temp_dir, "_opencode_prompt.txt")
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_text)

        env = os.environ.copy()
        env["DEEPSEEK_API_KEY"] = self._get_deepseek_key()
        env.pop("http_proxy", None)
        env.pop("https_proxy", None)
        env.pop("HTTP_PROXY", None)
        env.pop("HTTPS_PROXY", None)

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = f'PATH=/usr/local/bin:$PATH opencode run -m deepseek/deepseek-reasoner "$(cat {prompt_file})"'
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=600, env=env, cwd=project_root
            )
            output = result.stdout
            if not output:
                output = result.stderr or ""

            # 1. 去掉 ANSI 转义码
            output = re.sub(r'\x1b\[[0-9;]*m', '', output)
            output = re.sub(r'\033\[[0-9;]*m', '', output)
            # 真正的 ANSI 字节
            output = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', output)

            # 2. 提取 ```python ... ``` 代码块
            code_match = re.search(r'```python\s*\n(.*?)\n```', output, re.DOTALL)
            if code_match:
                code = code_match.group(1).strip()
                logger.info("opencode 返回代码 (%d 行)", code.count("\n") + 1)
                return code

            # 3. fallback: 提取 from manim import * 开始的内容
            manim_match = re.search(r'(from manim import \*.*)', output, re.DOTALL)
            if manim_match:
                code = manim_match.group(1).strip()
                # 去掉尾部的 ``` 标记
                code = re.sub(r'\n```\s*$', '', code)
                logger.info("opencode fallback 提取代码 (%d 行)", code.count("\n") + 1)
                return code

            logger.warning("opencode 未返回有效代码，输出前 500 字: %s", output[:500])
            return ""
        except subprocess.TimeoutExpired:
            logger.error("opencode 调用超时")
            return ""
        except Exception as e:
            logger.error("opencode 调用失败: %s", e)
            return ""

    def _get_config(self):
        """读取并缓存 config.yaml 配置。"""
        if self._config_cache is None:
            config_path = "config.yaml"
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self._config_cache = yaml.safe_load(f) or {}
            else:
                self._config_cache = {}
        return self._config_cache

    def _get_deepseek_key(self):
        config = self._get_config()
        return config.get("llm_api_key", "") or os.environ.get("LLM_API_KEY", "")

    # ------------------------------------------------------------------
    # Manim 代码生成
    # ------------------------------------------------------------------

    def generate_manim_code(self, scene_info):
        """根据场景信息调用 LLM 生成 ManimCE 代码。"""
        scene_type = scene_info.get("type", "formula")
        prompt_key = f"manim_generate_{scene_type}"
        prompt = prompts_dict.get(prompt_key, prompts_dict.get("manim_generate_formula", ""))

        sname = scene_info.get("scene_name", "CustomScene")
        sdesc = scene_info.get("description", "")
        user_content = f"scene_name: {sname}\n"
        user_content += f"描述: {sdesc}\n"
        if scene_info.get("latex"):
            user_content += f"LaTeX 公式: {scene_info['latex']}\n"
        if scene_info.get("script_excerpt"):
            user_content += f"脚本原文: {scene_info['script_excerpt']}\n"
        user_content += f"\n论文原文参考（前2000字）:\n{self.paper_text[:2000]}\n"
        user_content += "\n重要：生成的动画内容必须忠实于这篇论文的具体方法，不要用通用的示例。\n"

        full_prompt = prompt + "\n\n" + user_content
        logger.info("使用 opencode headless 生成 Manim 代码...")
        raw = self._opencode_generate(full_prompt)

        # 清理 markdown 代码块标记
        code = raw.strip()
        if code.startswith("```"):
            code = re.sub(r"^```\w*\n?", "", code)
            code = re.sub(r"\n?```$", "", code)
            code = code.strip()

        return code

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def render_scene(self, code, scene_name, quality="medium", fmt="mp4", max_retries=3):
        """渲染单个 Manim 场景。"""
        quality_flag = QUALITY_MAP.get(quality, "-qm")
        fmt_flag = "--format=gif" if fmt == "gif" else ""

        for attempt in range(max_retries):
            script_path = os.path.join(self.temp_dir, f"{scene_name}.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)

            cmd = f"manim render {quality_flag} {fmt_flag} --media_dir {self.output_dir}/media {script_path} {scene_name}"
            logger.info("渲染场景 %s (第 %d 次): %s", scene_name, attempt + 1, cmd)

            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=120
                )

                ext = "gif" if fmt == "gif" else "mp4"
                media_dir = os.path.join(self.output_dir, "media", "videos")
                found = glob.glob(os.path.join(media_dir, "**", f"{scene_name}.{ext}"), recursive=True)
                found = [f for f in found if "partial_movie_files" not in f]
                if found:
                    logger.info("场景 %s 渲染成功: %s", scene_name, found[0])
                    return found[0]

                if result.returncode == 0:
                    all_files = glob.glob(os.path.join(self.output_dir, "**", f"*.{ext}"), recursive=True)
                    all_files = [f for f in all_files if "partial_movie_files" not in f]
                    if all_files:
                        latest = max(all_files, key=os.path.getmtime)
                        logger.info("使用最新输出文件: %s", latest)
                        return latest

                error_msg = result.stderr or result.stdout
                logger.warning("场景 %s 渲染失败 (第 %d 次):\n%s", scene_name, attempt + 1, error_msg[:2000])

                if attempt < max_retries - 1:
                    fix_prompt = prompts_dict.get("manim_fix_code", "")
                    fix_content = f"原始代码:\n```python\n{code}\n```\n\n错误信息:\n```\n{error_msg[:3000]}\n```"
                    code = manim_chat(fix_prompt, fix_content)
                    code = code.strip()
                    if code.startswith("```"):
                        code = re.sub(r"^```\w*\n?", "", code)
                        code = re.sub(r"\n?```$", "", code)
                        code = code.strip()
                    logger.info("LLM 已修复代码，准备重试")

            except subprocess.TimeoutExpired:
                logger.error("场景 %s 渲染超时", scene_name)
            except Exception as e:
                logger.error("场景 %s 渲染异常: %s", scene_name, e)

        logger.error("场景 %s 渲染最终失败，已达最大重试次数", scene_name)
        return None

    # ------------------------------------------------------------------
    # Pipeline 图片加载（caption-based matching）
    # ------------------------------------------------------------------

    def load_pipeline_images(self):
        """从 pipeline 的 script.json 和 image_explanations 加载图片，按场景类型分配。"""
        pic_files = sorted(glob.glob("./pic/*.png"),
                          key=lambda x: int(re.findall(r"\d+", os.path.basename(x))[0])
                          if re.findall(r"\d+", os.path.basename(x)) else 0)

        if not pic_files:
            return {"opening": [], "intro": [], "method": [], "results": []}

        # 1. 优先从 script.json 读取（有最准确的 context/transition 信息）
        script_json = None
        for f in glob.glob("./src/output/*_script.json") + glob.glob("./output/*_script.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    script_json = json.load(fh)
                break
            except Exception:
                continue

        # 2. 或从 image_explanations.json 读取
        captions = {}
        expl_path = "./cache/image_explanations.json"
        if os.path.exists(expl_path):
            with open(expl_path, "r", encoding="utf-8") as f:
                explanations = json.load(f)
            for i, expl in enumerate(explanations):
                if i < len(pic_files):
                    captions[pic_files[i]] = {
                        "caption": expl.get("caption", ""),
                        "context": expl.get("context", ""),
                        "role": expl.get("figure_role", ""),
                        "section": expl.get("recommended_section", "method"),
                    }

        # 如果有 script.json，用它的 images 字段更新 captions
        if script_json and "images" in script_json:
            for img_info in script_json["images"]:
                idx = int(img_info.get("image_index", 0))
                if idx < len(pic_files):
                    captions[pic_files[idx]] = {
                        "caption": img_info.get("caption", ""),
                        "context": img_info.get("context", ""),
                        "role": "",
                        "section": "results" if "result" in img_info.get("context", "").lower() else "method",
                    }

        img_map = {"opening": [], "intro": [], "method": [], "results": []}

        # 按 caption/context 关键词匹配
        result_kws = ["table", "表", "result", "实验", "experiment", "performance", "ablation", "success"]
        method_kws = ["architecture", "架构", "pipeline", "framework", "模块", "method", "设计", "结构"]

        for path in pic_files:
            info = captions.get(path, {})
            text = (info.get("caption", "") + " " + info.get("context", "") + " " + info.get("section", "")).lower()

            if any(kw in text for kw in result_kws):
                img_map["results"].append(path)
            elif any(kw in text for kw in method_kws):
                img_map["method"].append(path)
            elif "intro" in text or "opening" in text:
                img_map["intro"].append(path)
            else:
                img_map["method"].append(path)

        # 确保 opening 有图片（用第一张 method 图或整体第一张）
        if not img_map["opening"]:
            if img_map["method"]:
                img_map["opening"] = [img_map["method"][0]]
            elif pic_files:
                img_map["opening"] = [pic_files[0]]
        if not img_map["intro"]:
            if len(img_map["method"]) > 1:
                img_map["intro"] = [img_map["method"][1]]
            elif img_map["method"]:
                img_map["intro"] = [img_map["method"][0]]

        logger.info("Pipeline 图片匹配: %s",
                    {k: [os.path.basename(p) for p in v] for k, v in img_map.items()})
        return img_map


    def generate_tts(self, scenes, narrations):
        """为场景生成 TTS 音频。

        Args:
            scenes: 场景列表。
            narrations: 与场景一一对应的讲解词列表。
        """
        try:
            import dashscope
            from dashscope.audio.tts_v2 import SpeechSynthesizer

            config = self._get_config()
            ds_key = config.get("dashscope_api_key", "")
            if ds_key:
                dashscope.api_key = ds_key

            audio_parts = []
            for i, text in enumerate(narrations):
                if not text or not text.strip():
                    continue

                audio_path = os.path.join(self.temp_dir, f"tts_{i}.mp3")
                synthesizer = SpeechSynthesizer(model="cosyvoice-v1", voice="longxiaochun")
                audio_data = synthesizer.call(text)

                if audio_data:
                    with open(audio_path, "wb") as f:
                        f.write(audio_data)
                    audio_parts.append(audio_path)
                    logger.info("TTS 第 %d 段生成成功: %s", i, text[:30])

            if not audio_parts:
                return None

            audio_clips = [AudioFileClip(p) for p in audio_parts]
            from moviepy import concatenate_audioclips
            combined = concatenate_audioclips(audio_clips)
            output_audio = os.path.join(self.temp_dir, "tts_combined.mp3")
            combined.write_audiofile(output_audio)

            for clip in audio_clips:
                clip.close()

            self._audio_parts = audio_parts  # 保存各段音频路径
            return output_audio

        except Exception as e:
            logger.warning("TTS 生成失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 拼接
    # ------------------------------------------------------------------

    def compose(self, scene_videos, tts_audio=None, fmt="mp4", scene_image_paths=None, narration_audios=None):
        """拼接所有场景视频为完整演示。"""
        import numpy as np
        from PIL import Image as PILImage

        if not scene_videos:
            logger.error("没有可拼接的视频片段")
            return None

        ext = "gif" if fmt == "gif" else "mp4"
        output_path = os.path.join(self.output_dir, f"manim_presentation.{ext}")

        final_clips = []

        for idx, vpath in enumerate(scene_videos):
            try:
                video = VideoFileClip(vpath)
            except Exception as e:
                logger.warning("加载视频片段失败 %s: %s", vpath, e)
                continue

            # 获取对应的音频
            audio = None
            if narration_audios and idx < len(narration_audios) and narration_audios[idx]:
                try:
                    audio = AudioFileClip(narration_audios[idx])
                except Exception:
                    pass

            # 如果音频比动画长，用 pipeline 图片填充
            if audio and audio.duration > video.duration:
                gap = audio.duration - video.duration + 1.0
                img_path = scene_image_paths[idx] if scene_image_paths and idx < len(scene_image_paths) else None

                if img_path and os.path.exists(img_path):
                    # 将 pipeline 图片做成视频片段
                    img = PILImage.open(img_path).convert("RGB")
                    w, h = video.w, video.h
                    max_w, max_h = int(w * 0.95), int(h * 0.95)
                    img_w, img_h = img.size
                    scale = min(max_w / img_w, max_h / img_h)
                    new_w, new_h = int(img_w * scale), int(img_h * scale)
                    img = img.resize((new_w, new_h), PILImage.LANCZOS)
                    bg = PILImage.new("RGB", (w, h), (0, 0, 0))
                    bg.paste(img, ((w - new_w) // 2, (h - new_h) // 2))
                    from moviepy import ImageClip
                    img_clip = ImageClip(np.array(bg), duration=gap)
                    video = concatenate_videoclips([video, img_clip])
                    logger.info("场景 %d: 动画后接 pipeline 图片 %s (%.1fs)", idx, img_path, gap)
                else:
                    # fallback: 冻结非黑帧
                    from moviepy import ImageClip
                    frame = video.get_frame(video.duration - 0.01)
                    if np.mean(frame) < 10:  # 全黑，回退找有内容的帧
                        for t in [video.duration*0.7, video.duration*0.5, video.duration*0.3, 1.0]:
                            f2 = video.get_frame(min(t, video.duration-0.01))
                            if np.mean(f2) > 10:
                                frame = f2
                                break
                    freeze = ImageClip(frame, duration=gap)
                    video = concatenate_videoclips([video, freeze])

            if audio:
                video = video.with_audio(audio)

            final_clips.append(video)

        if not final_clips:
            logger.error("所有视频片段加载失败")
            return None

        try:
            final = concatenate_videoclips(final_clips, method="compose")

            if fmt == "gif":
                final.write_gif(output_path, fps=15)
            else:
                final.write_videofile(output_path, fps=30, codec="libx264", audio_codec="aac")

            logger.info("演示视频已生成: %s", output_path)
            return output_path

        except Exception as e:
            logger.error("视频拼接失败: %s", e)
            return None
        finally:
            for clip in final_clips:
                try:
                    clip.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # 主流程: 固定 4 场景结构
    # ------------------------------------------------------------------


    def _assign_images_to_scenes(self, pipeline_images, scene_defs, rendered_indices):
        """为渲染成功的场景分配不重复的 pipeline 图片。"""
        scene_image_paths = []
        used_images = set()
        for i in rendered_indices:
            sec = scene_defs[i]["section"]
            # 按优先级找：本 section > method > 任意
            candidates = (pipeline_images.get(sec, []) +
                         pipeline_images.get("method", []))
            img = None
            for c in candidates:
                if c not in used_images:
                    img = c
                    used_images.add(c)
                    break
            # fallback: 任意未用过的图
            if not img:
                for imgs in pipeline_images.values():
                    for c in imgs:
                        if c not in used_images:
                            img = c
                            used_images.add(c)
                            break
                    if img:
                        break
            scene_image_paths.append(img)
            logger.info("场景 %s 分配图片: %s", scene_defs[i]["scene_name"],
                       os.path.basename(img) if img else "None")
        return scene_image_paths

    def run(self, tts=False, quality="medium", fmt="mp4"):
        """完整流程：固定 4 场景 -> 生成代码 -> 渲染 -> 拼接。"""
        logger.info("=== Manim 演示生成开始 ===")

        # 1. Extract scripts from structured_plan
        sections = ["opening", "intro", "method", "results"]
        plan_scripts = {}
        for sec in sections:
            sec_data = self.structured_plan.get(sec, {})
            script = sec_data.get("script", sec_data) if isinstance(sec_data, dict) else sec_data
            plan_scripts[sec] = str(script) if script else ""

        # 2. Define fixed 4 scenes
        scene_defs = [
            {
                "scene_name": "TitleScene",
                "type": "title",
                "section": "opening",
                "description": f"论文标题和开场。脚本: {plan_scripts.get('opening', '')[:200]}",
            },
            {
                "scene_name": "IntroScene",
                "type": "flow",
                "section": "intro",
                "description": f"背景介绍和问题引出。脚本: {plan_scripts.get('intro', '')[:200]}",
            },
            {
                "scene_name": "MethodScene",
                "type": "architecture",
                "section": "method",
                "description": f"核心方法展示。脚本: {plan_scripts.get('method', '')[:200]}",
            },
            {
                "scene_name": "ResultsScene",
                "type": "results",
                "section": "results",
                "description": f"实验结果展示。脚本: {plan_scripts.get('results', '')[:200]}",
            },
        ]

        # 3. Narrations = plan scripts directly
        narrations = [plan_scripts.get(s["section"], "") for s in scene_defs]

        # 4. Generate + render each scene
        scene_videos = []
        rendered_indices = []
        for i, sdef in enumerate(scene_defs):
            logger.info("生成场景 %d/4: %s (%s)", i + 1, sdef["scene_name"], sdef["type"])
            code = self.generate_manim_code(sdef)
            if not code:
                logger.warning("场景 %s 代码生成失败，跳过", sdef["scene_name"])
                continue
            # Inject bounds check
            code = self.inject_bounds_check(code)
            video_path = self.render_scene(code, sdef["scene_name"], quality=quality, fmt=fmt)
            if video_path:
                scene_videos.append(video_path)
                rendered_indices.append(i)
            else:
                logger.warning("场景 %s 渲染失败，跳过", sdef["scene_name"])

        if not scene_videos:
            logger.error("所有场景渲染失败")
            return None

        # 5. TTS for rendered scenes
        audio_paths = []
        if tts:
            rendered_narrations = [narrations[i] for i in rendered_indices]
            self.generate_tts(scene_defs, rendered_narrations)
            audio_paths = getattr(self, "_audio_parts", [])

        # 6. Load pipeline images + compose
        pipeline_images = self.load_pipeline_images()
        scene_image_paths = self._assign_images_to_scenes(
            pipeline_images, scene_defs, rendered_indices
        )

        output = self.compose(
            scene_videos,
            fmt=fmt,
            scene_image_paths=scene_image_paths,
            narration_audios=audio_paths,
        )

        if output:
            logger.info("=== Manim 演示生成完成: %s ===", output)
        return output
