# -*- coding: utf-8 -*-
import os
import logging
from typing import Optional, Dict, Any

# 兼容作为包导入与脚本直接运行
try:
    from src.config import TESSDATA_PREFIX, OUTPUT_LANGUAGE
except Exception:  # pragma: no cover
    from config import TESSDATA_PREFIX, OUTPUT_LANGUAGE  # type: ignore


def diagnose_text_extraction(pdf_path: str, lang: Optional[str] = None, max_pages: int = 2) -> Dict[str, Any]:
    """
    诊断 PDF 文本提取：优先使用 PyMuPDF(page.get_text) 提取内嵌文本（参考 pdf_processor.extract_text），
    当内嵌文本过少时回退到 OCR(pytesseract)。同时检测 deepdoctection 可用性。

    参数：
    - pdf_path: PDF 文件路径
    - lang: OCR 语言，None 时根据 OUTPUT_LANGUAGE 自动选择（zh -> chi_sim, en -> eng）
    - max_pages: OCR 处理的最大页数（避免过慢）

    返回：
    - dict，包含各环节长度/错误/环境信息
    """
    info: Dict[str, Any] = {
        "pdf_path": pdf_path,
        "tessdata_prefix": TESSDATA_PREFIX,
        "output_language": OUTPUT_LANGUAGE,
        "language_used": None,
        "pymupdf_text_len": 0,
        "pdfminer_text_len": 0,
        "pytesseract_text_len": 0,
        "pytesseract_error": None,
        "deepdoctection_available": False,
        "deepdoctection_error": None,
        "pages_processed": 0,
    }

    # 1) PyMuPDF 提取内嵌文本（与 pdf_processor.extract_text 保持一致）
    try:
        import fitz  # PyMuPDF
        text_embed = ""
        with fitz.open(pdf_path) as doc:  # type: ignore[arg-type]
            for page in doc:
                text_embed += page.get_text()
        info["pymupdf_text_len"] = len(text_embed or "")
    except Exception as e:
        logging.warning("PyMuPDF 提取失败: %s", e)

    # 2) 可选：pdfminer 再试一遍（用于对比）
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract_text
        text_pdfminer = pdfminer_extract_text(pdf_path)
        info["pdfminer_text_len"] = len(text_pdfminer or "")
    except Exception as e:
        logging.warning("pdfminer 提取失败: %s", e)

    # 3) 若内嵌文本较少（例如扫描件），使用 OCR 回退
    try:
        need_ocr = (info["pymupdf_text_len"] < 50) and (info["pdfminer_text_len"] < 50)
        if need_ocr:
            import pytesseract
            try:
                from pdf2image import convert_from_path
            except Exception as e:
                raise RuntimeError(f"pdf2image 不可用或缺少 poppler 支持: {e}")

            # 设置语言
            if lang is None:
                lang = "chi_sim" if (OUTPUT_LANGUAGE or "zh").lower().startswith("zh") else "eng"
            info["language_used"] = lang

            # 确保 TESSDATA_PREFIX 生效
            if TESSDATA_PREFIX and not os.environ.get("TESSDATA_PREFIX"):
                os.environ["TESSDATA_PREFIX"] = str(TESSDATA_PREFIX)

            # 将前 max_pages 页渲染为图像
            images = convert_from_path(pdf_path, dpi=300, first_page=1, last_page=max_pages)
            info["pages_processed"] = len(images)

            ocr_text_parts = []
            for img in images:
                ocr_text_parts.append(pytesseract.image_to_string(img, lang=lang))
            ocr_text = "\n".join(ocr_text_parts)
            info["pytesseract_text_len"] = len(ocr_text or "")
    except Exception as e:
        info["pytesseract_error"] = str(e)

    # 4) 检查 deepdoctection 是否可用（版面分析库）
    try:
        import deepdoctection  # type: ignore  # noqa: F401
        info["deepdoctection_available"] = True
    except Exception as e:
        info["deepdoctection_error"] = str(e)

    # 结论提示（日志）
    if info["deepdoctection_available"] is False:
        logging.info("deepdoctection 不可用：%s", info["deepdoctection_error"])
        logging.info("说明：deepdoctection 主要做版面分析，若无 OCR 后端或模型未就绪，无法直接输出文字。")
    if info["pytesseract_error"]:
        logging.info("OCR 失败：%s", info["pytesseract_error"]) 
        logging.info("请检查：1) 是否安装 tesseract 及中文语言包 chi_sim；2) TESSDATA_PREFIX 是否正确；3) 是否安装 poppler（pdf2image 依赖）")

    return info


if __name__ == "__main__":  # 便捷测试：python src/ocr_diagnostics.py /path/to.pdf
    import sys, json
    _path = sys.argv[1] if len(sys.argv) > 1 else ""
    if not _path:
        print("Usage: python src/ocr_diagnostics.py /path/to.pdf")
        raise SystemExit(2)
    res = diagnose_text_extraction(_path)
    print(json.dumps(res, ensure_ascii=False, indent=2))

__all__ = ["diagnose_text_extraction"]
