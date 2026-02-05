# -*- coding: utf-8 -*-
"""
Caption 提取模块

功能：
1. 使用 PyMuPDF 提取 PDF 全部文字
2. 使用 LLM Agent 将文字解析成 caption
3. 以 JSON 形式存储，返回字典格式

返回格式：
{"fig_1": "图片标题1", "tab_1": "表格标题1", ...}
"""

import os
import json
import logging
from typing import Dict, Any, Optional

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

try:
    import fitz  # PyMuPDF
except ImportError:
    logging.error("请安装 PyMuPDF: pip install PyMuPDF")
    raise

from llm_tools.llm_agent import extract_captions_to_dict


class CaptionExtractor:
    """Caption 提取器"""
    
    def __init__(self, pdf_path: str):
        """
        初始化 Caption 提取器
        
        参数:
        - pdf_path: PDF 文件路径
        """
        self.pdf_path = pdf_path
        self.captions = {}
        
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")
    
    def extract_text_from_pdf(self) -> str:
        """
        使用 PyMuPDF 提取 PDF 全部文字
        
        返回:
        - str: 提取的全部文本
        """
        logging.info(f"开始从 PDF 提取文字: {self.pdf_path}")
        
        try:
            text = ""
            with fitz.open(self.pdf_path) as doc:
                for page_num, page in enumerate(doc, 1):
                    page_text = page.get_text()
                    text += page_text
                    logging.debug(f"第 {page_num} 页提取文字长度: {len(page_text)}")
            
            logging.info(f"PDF 文字提取完成，总长度: {len(text)} 字符")
            return text
            
        except Exception as e:
            logging.error(f"PDF 文字提取失败: {e}")
            raise
    
    def extract_captions_with_llm(self, text: str) -> Dict[str, str]:
        """
        使用 LLM Agent 从文本中提取 caption
        
        参数:
        - text: 待解析的文本
        
        返回:
        - Dict[str, str]: {"fig_1": "caption1", "tab_1": "caption1", ...}
        """
        logging.info("开始使用 LLM 提取 caption")
        
        try:
            captions_dict = extract_captions_to_dict(text)
            
            if not isinstance(captions_dict, dict):
                logging.warning("LLM 返回的不是字典格式，返回空字典")
                return {}
            
            logging.info(f"成功提取 {len(captions_dict)} 个 caption")
            
            # 记录提取的 caption
            for key, value in captions_dict.items():
                logging.info(f"{key}: {value[:100]}...")  # 只显示前100个字符
            
            return captions_dict
            
        except Exception as e:
            logging.error(f"LLM caption 提取失败: {e}")
            return {}
    
    def extract_captions(self) -> Dict[str, str]:
        """
        完整的 caption 提取流程
        
        返回:
        - Dict[str, str]: {"fig_1": "caption1", "tab_1": "caption1", ...}
        """
        # 步骤1: 提取PDF文字
        text = self.extract_text_from_pdf()
        
        if not text.strip():
            logging.warning("PDF 中没有提取到文字")
            return {}
        
        # 步骤2: 使用LLM提取caption
        captions = self.extract_captions_with_llm(text)
        
        # 保存结果
        self.captions = captions
        
        return captions
    
    def save_to_json(self, output_path: str) -> None:
        """
        将提取的 caption 保存为 JSON 文件
        
        参数:
        - output_path: 输出文件路径
        """
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(self.captions, f, ensure_ascii=False, indent=2)
            
            logging.info(f"Caption 已保存到: {output_path}")
            
        except Exception as e:
            logging.error(f"保存 JSON 文件失败: {e}")
            raise


def extract_captions_from_pdf(pdf_path: str, output_path: Optional[str] = None) -> Dict[str, str]:
    """
    从 PDF 提取 caption 的便捷函数
    
    参数:
    - pdf_path: PDF 文件路径
    - output_path: 可选的 JSON 输出路径
    
    返回:
    - Dict[str, str]: {"fig_1": "caption1", "tab_1": "caption1", ...}
    """
    extractor = CaptionExtractor(pdf_path)
    captions = extractor.extract_captions()
    
    if output_path:
        extractor.save_to_json(output_path)
    
    return captions


def main():
    """测试函数"""
    import sys
    
    # 测试用的 PDF 路径
    test_pdf_path = "/home/jdh/Projects/VlogCutter/JushenRenji/cached_pdf.pdf"
    
    # 如果命令行提供了路径，使用命令行参数
    if len(sys.argv) > 1:
        test_pdf_path = sys.argv[1]
    
    print(f"🔍 开始测试 Caption 提取功能")
    print(f"📄 PDF 文件: {test_pdf_path}")
    print("=" * 60)
    
    try:
        # 测试提取功能
        captions = extract_captions_from_pdf(
            pdf_path=test_pdf_path,
            output_path="./cache/extracted_captions.json"
        )
        
        print(f"✅ Caption 提取完成！")
        print(f"📊 共提取到 {len(captions)} 个 caption")
        print("\n📋 提取结果:")
        print("-" * 40)
        
        if captions:
            for key, value in captions.items():
                print(f"{key}: {value}")
        else:
            print("❌ 未提取到任何 caption")
        
        print("\n" + "=" * 60)
        print(f"💾 结果已保存到: ./cache/extracted_captions.json")
        
        # 返回结果用于进一步测试
        return captions
        
    except FileNotFoundError:
        print(f"❌ 错误: PDF 文件不存在: {test_pdf_path}")
        print("💡 请确保文件路径正确，或使用命令行参数指定PDF路径:")
        print(f"   python {__file__} /path/to/your.pdf")
        return {}
        
    except Exception as e:
        print(f"❌ 提取过程发生错误: {e}")
        logging.exception("Caption 提取测试失败")
        return {}


if __name__ == "__main__":
    main()
