#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image agent for qwen-vl (multi-modal) integration.

Features:
- explain_image: single image + optional caption/context -> structured JSON explanation
- explain_images: batch explain_images with concurrency and optional contexts mapping

Notes:
- Uses DashScope / Model Studio compatible endpoint. The project already sets
  `dashscope.api_key` in `llm_tools.llm_agent.initialize_agent()` so this module
  will reuse `dashscope.api_key` when available. The same key is used for qwen-vl
  according to user instructions.
- If qwen-vl endpoint is not reachable, falls back to OCR + text LLM (via
  `llm_tools.llm_agent.create_chat_completion`) when enabled.
"""

import os
import io
import re
import json
import base64
import logging
from typing import Any, Dict, List, Optional
import uuid
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

try:  # optional dependency for OCR fallback
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover
    pytesseract = None

import requests

try:
    import dashscope
except Exception:
    dashscope = None

from src.llm_tools import llm_agent as _llm_agent
from src.llm_tools.llm_agent import _parse_json_response
from src.config import DASHSCOPE_API_KEY
from src.llm_tools.prompts import prompts_dict, get_language_suffix

logger = logging.getLogger(__name__)


def _image_to_base64(image: Any) -> str:
    """Accept PIL.Image, bytes, or a local path string. Return base64 string."""
    if isinstance(image, str):
        # treat as path
        with open(image, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode()
    if isinstance(image, bytes):
        return base64.b64encode(image).decode()
    # PIL Image
    if Image and isinstance(image, Image.Image):
        buf = io.BytesIO()
        # save as JPEG to reduce size
        image.convert("RGB").save(buf, format="JPEG", quality=90)
        return base64.b64encode(buf.getvalue()).decode()
    raise TypeError("Unsupported image type for base64 conversion")


def _extract_json_from_text(text: str) -> Optional[Dict]:
    """Extract JSON from LLM text. Delegates to the canonical _parse_json_response."""
    # 清理LLM返回的内容，移除markdown代码块标记
    cleaned_text = text.strip()
    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[7:]
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3]
    cleaned_text = cleaned_text.strip()

    result = _parse_json_response(cleaned_text)
    return result or None


class ImageAgent:
    def __init__(self, model: str = "qwen3-vl-plus", timeout: int = 30, ocr_fallback: bool = True):
        # base_url is no longer needed because DashScope SDK resolves it automatically
        self.model = model or 'qwen3-vl-plus'
        self.timeout = timeout
        self.ocr_fallback = ocr_fallback

    def explain_image(self, image: Any, caption_text: Optional[str] = None,
                      paper_abstract: Optional[str] = None, paper_text: Optional[str] = None,
                      per_image_budget: int = 150, lang: str = "zh") -> Dict[str, Any]:
        """Explain a single image using qwen-vl.

        Returns a dict with keys: id(optional), caption, detailed_explanation, key_points, qa
        caption_text: optional figure caption or context
        paper_abstract: optional abstract text to enrich the explanation
        paper_text: optional full paper text to provide comprehensive context
        """
        # Prepare an image reference suitable for DashScope SDK
        temp_path: Optional[Path] = None
        image_ref = None
        try:
            if isinstance(image, str):
                # URL or local path
                if image.startswith('http://') or image.startswith('https://'):
                    image_ref = image
                elif image.startswith('file://'):
                    image_ref = image
                else:
                    # treat as local path
                    abs_path = Path(image).resolve()
                    image_ref = f"file://{abs_path}"
            elif isinstance(image, bytes):
                # write to temp file
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
                tmp.write(image)
                tmp.close()
                temp_path = Path(tmp.name)
                image_ref = f"file://{temp_path.resolve()}"
            elif Image and isinstance(image, Image.Image):
                # save PIL Image to temp file
                tmpfile = Path(tempfile.gettempdir()) / f"img_{uuid.uuid4().hex}.jpg"
                image.save(tmpfile, format='JPEG', quality=90)
                temp_path = tmpfile
                image_ref = f"file://{temp_path.resolve()}"
            else:
                raise TypeError("Unsupported image type for DashScope call")

            # Build messages following DashScope MultiModalConversation example
            raw_system = prompts_dict.get("explain_image_system", "")
            system_prompt = raw_system.format(per_image_budget=per_image_budget)
            system_msg = {
                "role": "system",
                "content": [
                    {
                        "text": system_prompt
                    }
                ]
            }

            trimmed_caption = caption_text.strip() if caption_text else ""
            trimmed_abstract = paper_abstract.strip() if paper_abstract else ""
            trimmed_paper_text = paper_text.strip() if paper_text else ""
            if trimmed_abstract:
                # cap overly long abstracts to keep prompt length manageable
                trimmed_abstract = trimmed_abstract[:1500]
            if trimmed_paper_text:
                # cap overly long paper text to keep prompt length manageable
                trimmed_paper_text = trimmed_paper_text[:3000]

            base_user_prompt = prompts_dict.get("explain_image_user", "").format(per_image_budget=per_image_budget)

            prompt_parts = [base_user_prompt]
            if trimmed_caption:
                prompt_parts.append(f"\n图像题注：{trimmed_caption}")
            if trimmed_abstract:
                prompt_parts.append(f"\n论文摘要：{trimmed_abstract}")
            if trimmed_paper_text:
                prompt_parts.append(f"\n论文全文（节选）：{trimmed_paper_text}")

            user_content = [
                {"image": image_ref},
                {"text": " ".join(prompt_parts)}
            ]
            messages = [
                system_msg,
                {
                    "role": "user",
                    "content": user_content
                }
            ]

            # prefer config.DASHSCOPE_API_KEY (loaded from config.yaml) or llm_agent client
            api_key = DASHSCOPE_API_KEY or None
            if not api_key:
                try:
                    api_key = _llm_agent.client.api_key  # type: ignore[attr-defined]
                except Exception:
                    api_key = None

            if not dashscope:
                raise RuntimeError('dashscope SDK not available')

            # call DashScope MultiModalConversation
            resp = dashscope.MultiModalConversation.call(
                api_key=api_key,
                model=self.model,
                messages=messages,
            )

            # extract text from response
            try:
                if hasattr(resp, 'status_code') and resp.status_code != 200:
                    # If API returned error, raise it
                    raise RuntimeError(f"DashScope API Error: {getattr(resp, 'code', 'Unknown')} - {getattr(resp, 'message', str(resp))}")

                # As per user request/example: response.output.choices[0].message.content[0]["text"]
                text = resp.output.choices[0].message.content[0]["text"]
            except Exception as e:
                logger.error(f"Failed to parse response: {resp}")
                import traceback
                logger.error(traceback.format_exc())
                raise RuntimeError(f"Response parsing failed: {e}")

            parsed = _extract_json_from_text(text)
            result = parsed if parsed else {"raw_text": text}
            if isinstance(result, dict):
                result = self._normalize_outputs(result)
            return result

        except Exception as e:
            logger.warning("DashScope MultiModalConversation failed: %s", e)
            if self.ocr_fallback:
                logger.info("使用 OCR 回退路径进行图像解释")
                try:
                    return self._ocr_fallback_explain(image, caption_text, paper_abstract=paper_abstract, paper_text=paper_text)
                except Exception as e2:
                    logger.error("OCR fallback also failed: %s", e2)
                    return {"error": str(e2)}
            return {"error": str(e)}
        finally:
            # cleanup temp file if created
            try:
                if temp_path and temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass

    def _ocr_fallback_explain(self, image: Any, caption_text: Optional[str] = None,
                              paper_abstract: Optional[str] = None, paper_text: Optional[str] = None) -> Dict[str, Any]:
        # Use pytesseract to extract text then use LLM text completion
        if not pytesseract:
            raise RuntimeError("pytesseract not available")

        # Convert image to PIL if needed
        pil_img = image
        if not isinstance(image, Image.Image):
            # try to open bytes or path
            if isinstance(image, (bytes, str)):
                from PIL import Image as PILImage
                if isinstance(image, bytes):
                    pil_img = PILImage.open(io.BytesIO(image))
                else:
                    pil_img = PILImage.open(image)
            else:
                raise TypeError("Unsupported image for OCR fallback")

        ocr_text = pytesseract.image_to_string(pil_img, lang='chi_sim') if pil_img else ''
        # merge with caption, abstract, and optional paper text
        merged_parts = [caption_text or "", paper_abstract or "", paper_text or "", ocr_text or ""]
        merged = "\n".join([part for part in merged_parts if part])
        ocr_prompt = prompts_dict.get("explain_image_ocr_fallback", "") + get_language_suffix()
        prompt = ocr_prompt + "\n" + merged
        try:
            ret = _llm_agent.create_chat_completion(prompt)
            parsed = _extract_json_from_text(ret)
            if parsed:
                return parsed
            return {"raw_text": ret}
        except Exception as e:
            logger.error("LLM text completion failed in OCR fallback: %s", e)
            raise

    def explain_images(self, images: List[Any], contexts: Optional[Dict[int, str]] = None,
                       paper_abstract: Optional[str] = None, paper_text: Optional[str] = None,
                       per_image_budget: int = 150, concurrency: int = 4) -> List[Dict[str, Any]]:
        """Explain a list of images. contexts maps 1-based index -> caption text."""
        results: List[Dict[str, Any]] = [None] * len(images)

        def _worker(idx, img):
            cap = None
            if contexts and (idx + 1) in contexts:
                cap = contexts[idx + 1]
            return idx, self.explain_image(img, caption_text=cap, paper_abstract=paper_abstract, paper_text=paper_text, per_image_budget=per_image_budget)

        with ThreadPoolExecutor(max_workers=concurrency) as exe:
            futures = [exe.submit(_worker, i, img) for i, img in enumerate(images)]
            for f in as_completed(futures):
                try:
                    idx, out = f.result()
                    results[idx] = out
                except Exception as e:
                    logger.error("explain_images worker failed: %s", e)
                    # keep None or error
                    results[idx] = {"error": str(e)}

        return results

    @staticmethod
    def _normalize_text(value: str) -> str:
        if not isinstance(value, str):
            return value
        return re.sub(r"\s+", " ", value).strip()

    def _normalize_outputs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = {}
        for key, val in payload.items():
            if key == "main_figure_score":
                try:
                    score = float(val)
                except (TypeError, ValueError):
                    score = 0.0
                normalized[key] = max(0.0, min(1.0, score))
            elif key == "key_points" and isinstance(val, list):
                normalized[key] = [self._normalize_text(item) for item in val if isinstance(item, str) and item.strip()]
            elif key == "qa" and isinstance(val, list):
                qa_list: List[Dict[str, Any]] = []
                for qa_item in val:
                    if isinstance(qa_item, dict):
                        qa_list.append({k: self._normalize_text(v) if isinstance(v, str) else v for k, v in qa_item.items()})
                normalized[key] = qa_list
            elif isinstance(val, str):
                normalized[key] = self._normalize_text(val)
            else:
                normalized[key] = val
        return normalized


__all__ = ["ImageAgent"]
