from PIL import Image, ImageDraw, ImageFont
import io
import fitz  # PyMuPDF
from dashscope import MultiModalConversation
from extract_images_from_pdf import extract_images_from_pdf
import logging

# 配置日志记录
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,  # 修改为 DEBUG 级别
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class PDFProcessor:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        try:
            self.doc = fitz.open(self.pdf_path)
            logging.info(f"成功打开PDF文件: {self.pdf_path}")
        except RuntimeError as e:
            logging.error(f"无法打开PDF文件: {e}")
            self.doc = None

    def extract_text(self):
        if not self.doc:
            logging.warning("文档未加载，无法提取文本")
            return ""
        logging.info("开始提取文本")
        text = ""
        for page in self.doc:
            text += page.get_text()
        logging.info("文本提取完成")
        return text

    def extract_images(self,cnt=None):
        extract_images_from_pdf(self.pdf_path,cnt=cnt)