import deepdoctection as dd
from IPython.core.display import HTML
from matplotlib import pyplot as plt
import os  # 添加导入 os 模块
import tempfile  # 添加导入 tempfile 模块
from PIL import Image  # 添加导入 PIL 库
# import garbgage collection
import gc
# 将 Tesseract-OCR 添加到 PATH 环境变量
os.environ['PATH'] += r";C:\Program Files\Tesseract-OCR"
# 设置 TESSDATA_PREFIX 环境变量
os.environ['TESSDATA_PREFIX'] = r"C:\Program Files\Tesseract-OCR\tessdata\tessdata_best-4.1.0"
# 设置临时目录路径
temp_dir = tempfile.gettempdir()
os.environ['TMPDIR'] = temp_dir
os.environ['TEMP'] = temp_dir
os.environ['TMP'] = temp_dir
# PDF_PATH = r".\mambaout.pdf"   
# extract_images_from_pdf(PDF_PATH) 
def extract_images_from_pdf(pdf_path,cnt=None,store_path='./pic/'):  
    analyzer = dd.get_dd_analyzer()  # instantiate the built-in analyzer similar to the Hugging Face space demo
    df = analyzer.analyze(path = pdf_path)  # setting up pipeline
    df.reset_state()   # Trigger some initialization
    doc = iter(df)
# 遍历 PDF 中的每一页
    figure_table_counter=0
    for i, page in enumerate(doc):
        for figure in page.figures:
            figure_table_counter+=1
            print(f"Figure {figure_table_counter} found on page {i+1}")
        # print(figure)
            img=figure.image.viz(show_cells=False,show_layouts=False,scaled_width=1920)
            img=Image.fromarray(img)
        #save img
            img.save(os.path.join(store_path,f'{figure_table_counter}.png'))
        for table in page.tables:
            figure_table_counter+=1
            print(f"Table {figure_table_counter} found on page {i+1}")
            print(table)
            img=table.image.viz(show_cells=False,show_layouts=False,scaled_width=1920)
            img=Image.fromarray(img)
            img.save(os.path.join(store_path,f'{figure_table_counter}.png'))
        if cnt and figure_table_counter>=cnt:
            break
        gc.collect()
        
        

        
        


        
        

