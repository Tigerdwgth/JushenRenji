from PIL import Image, ImageDraw, ImageFont
import io
import fitz  # PyMuPDF
from dashscope import MultiModalConversation
from extract_images_from_pdf import extract_images_from_pdf





class PDFProcessor:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        try:
            self.doc = fitz.open(self.pdf_path)
            print(f"成功打开PDF文件: {self.pdf_path}")
        except RuntimeError as e:
            print(f"无法打开PDF文件: {e}")
            self.doc = None

    def extract_text(self):
        if not self.doc:
            print("文档未加载，无法提取文本")
            return ""
        print("开始提取文本")
        text = ""
        for page in self.doc:
            text += page.get_text()
        print("文本提取完成")
        return text

    def extract_images(self):
        extract_images_from_pdf(self.pdf_path)