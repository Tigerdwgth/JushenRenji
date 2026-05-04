# deepdoctection 在 docker 构建因 numpy<2 冲突已禁用; 失败时函数体 try/except 兜底
try:
    import deepdoctection as dd
    from deepdoctection.utils.settings import LayoutType, Relationships
    from deepdoctection.datapoint.view import Page
    _DD_AVAILABLE = True
except ImportError as _e:
    dd = None  # type: ignore
    LayoutType = Relationships = Page = None  # type: ignore
    _DD_AVAILABLE = False
    import logging as _logging
    _logging.warning("deepdoctection 不可用, extract_images_from_pdf 将跳过: %s", _e)
try:
    from IPython.core.display import HTML  # type: ignore
except ImportError:
    HTML = None  # type: ignore
from matplotlib import pyplot as plt
import os  # 添加导入 os 模块
import tempfile  # 添加导入 tempfile 模块
from PIL import Image  # 添加导入 PIL 库
import logging  # 添加导入 logging 模块
from src.llm_tools.llm_agent import *
# import garbgage collection

# 将 Tesseract-OCR 添加到 PATH 环境变量
os.environ['PATH'] += r";C:\Program Files\Tesseract-OCR"
# 设置 TESSDATA_PREFIX 环境变量
os.environ['TESSDATA_PREFIX'] = r"/home/jdh/Projects/VlogCutter/JushenRenji/font"
# 设置临时目录路径
temp_dir = tempfile.gettempdir()
os.environ['TMPDIR'] = temp_dir
os.environ['TEMP'] = temp_dir
os.environ['TMP'] = temp_dir
os.environ['DD_USE_TORCH']="True"  # 确保使用 PyTorch 后端
os.environ['DD_USE_TF']="False"  # 禁用 TensorFlow 后端
os.environ["USE_CUDA"]="True"

# 配置日志记录
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,  # 修改为 DEBUG 级别
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# PDF_PATH = r".\mambaout.pdf"   
# extract_images_from_pdf(PDF_PATH) 
def extract_images_from_pdf(pdf_path, cnt=None, store_path='./pic/'):
    if not _DD_AVAILABLE:
        logging.warning('deepdoctection 不可用, 走 PyMuPDF 兜底提取 (能拿到 raw images, 没有 figure 版面框)')
        try:
            import fitz  # PyMuPDF
        except ImportError as e:
            logging.error('PyMuPDF 也不可用, 无法提取图片: %s', e)
            return
        os.makedirs(store_path, exist_ok=True)
        doc = fitz.open(pdf_path)
        figure_table_counter = 0
        for page_idx, page in enumerate(doc):
            for img_info in page.get_images(full=True):
                try:
                    figure_table_counter += 1
                    xref = img_info[0]
                    base = doc.extract_image(xref)
                    img_bytes = base['image']
                    ext = base.get('ext', 'png')
                    out_path = os.path.join(store_path, f'{figure_table_counter}.png')
                    if ext.lower() == 'png':
                        with open(out_path, 'wb') as fh:
                            fh.write(img_bytes)
                    else:
                        # convert to png via PIL
                        import io as _io
                        Image.open(_io.BytesIO(img_bytes)).convert('RGB').save(out_path, 'PNG')
                    logging.info('PyMuPDF: 第 %d 页第 %d 个图片 -> %s', page_idx + 1, figure_table_counter, out_path)
                    if cnt and figure_table_counter >= cnt:
                        doc.close()
                        return
                except Exception as e:
                    logging.warning('PyMuPDF: 处理 xref=%s 失败: %s', img_info[0] if img_info else '?', e)
        doc.close()
        logging.info('PyMuPDF: 共提取 %d 张图片到 %s', figure_table_counter, store_path)
        return
    try:
        analyzer = dd.get_dd_analyzer(config_overwrite=["USE_OCR=False"])  # 禁用OCR避免tesseract错误中断图片提取
        df = analyzer.analyze(path=pdf_path)  # setting up pipeline
        df.reset_state()  # Trigger some initialization
        doc = iter(df)
        # 遍历 PDF 中的每一页
        figure_table_counter = 0
        for i, page in enumerate(doc):
            text= page.text
            for figure in page.figures:
                try:
                    figure_table_counter += 1
                    captions = [ann.text for ann in page.get_annotation(category_names=LayoutType.CAPTION)]
                    logging.info(f"Figure {figure_table_counter} found on page {i+1} with captions: {captions}")
                    img = figure.image.viz(show_cells=False, show_layouts=False, scaled_width=1920)
                    img = Image.fromarray(img)
                    os.makedirs(store_path, exist_ok=True)  # 确保目录存在
                    # 保存图片
                    img.save(os.path.join(store_path, f'{figure_table_counter}.png'))
                except Exception as e:
                    logging.error(f"Error processing figure {figure_table_counter} on page {i+1}: {e}", exc_info=True)

            for table in page.tables:
                try:
                    figure_table_counter += 1
                    logging.info("Table %d found on page %d", figure_table_counter, i + 1)
                    img = table.image.viz(show_cells=False, show_layouts=False, scaled_width=1920)
                    img = Image.fromarray(img)
                    os.makedirs(store_path, exist_ok=True)  # 确保目录存在
                    img.save(os.path.join(store_path, f'{figure_table_counter}.png'))
                except Exception as e:
                    logging.error("Error processing table %d on page %d: %s", figure_table_counter, i + 1, e, exc_info=True)

            if cnt and figure_table_counter >= cnt:
                break
    except Exception as e:
        logging.error("Error in extract_images_from_pdf: %s", e, exc_info=True)










