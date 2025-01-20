from PIL import Image, ImageDraw, ImageFont
import io
import fitz  # PyMuPDF
from dashscope import MultiModalConversation






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
        """
        Extracts images and tables from a PDF file.

        Args:
            pdf_path (str): The path to the PDF file.

        Returns:
            list: A list of dictionaries, each containing information about an extracted image or table.
                  Each dictionary has the following keys:
                  - "type" (str): The type of the item, either "image" or "table".
                  - "page" (int): The page number where the item was found.
                  - "nested" (bool): Whether the item is from a nested PDF.
                  - "image_data" (bytes): The image data in bytes.
                  - "ext" (str): The image file extension.
                  - "bbox" (tuple): The bounding box of the image.
                  - "position" (tuple): The position of the image on the page.
        """

        pdf = self.doc
        images = []  # 用于存储所有图片和表格的数组

        def save_image(image_bytes, image_ext, page_number, bbox, position, item_type="image", nested=False):
            """保存图片到数组中"""
            images.append({
                "type": item_type,  # "image" 或 "table"
                "page": page_number,
                "nested": nested,  # 是否嵌套
                "image_data": image_bytes,
                "ext": image_ext,
                "bbox": bbox,
                "position": position
            })

        def extract_tables(page, page_number):
            """从页面提取表格（保存为图片）"""
            tabs = page.find_tables()
            positions=[]
            for tab in tabs:
                # 从页面中提取表格的区域
                bbox = tab.bbox
                positions.append(bbox)
            if len(positions) == 0:
                return   
            x0 = min([pos[0] for pos in positions])
            y0 = min([pos[1] for pos in positions])
            x1 = max([pos[2] for pos in positions])
            y1 = max([pos[3] for pos in positions])
            # 从页面中提取图片的区域
            bbox = fitz.Rect(x0, y0, x1, y1)    
            tab_pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=bbox)
            image_bytes = tab_pix.tobytes("png")
            save_image(image_bytes, "png", page_number, bbox, (0,0), item_type="table")
            print(f"在第 {page_number} 页找到表格")

        def extract_regular_images(page, page_number):
            """从页面中提取普通图片"""
            images_on_page = page.get_images()
            #每一页最多截一张图
            positions = []
            for img in images_on_page:
                xref = img[0]
                base_image = pdf.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                bbox = fitz.Rect(img[1:5])
                print(f"图片的坐标: {bbox}")
                positions.append(bbox)
                
                
            if len(positions) == 0:
                return
            else:
                # 找到一bbox可以包含所有的图片
                x0 = min([pos.x0 for pos in positions])
                y0 = min([pos.y0 for pos in positions])
                x1 = max([pos.x1 for pos in positions])
                y1 = max([pos.y1 for pos in positions])
                # 从页面中提取图片的区域
                bbox = fitz.Rect(x0, y0, x1, y1)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=bbox)
                
                   
            save_image(image_bytes, image_ext, page_number, bbox, (0,0,0,0))
            print(f"在第 {page_number} 页找到图片")

        def extract_nested_pdfs(page, page_number):
            """从嵌套 PDF 中提取图片"""
            for xref in range(1, pdf.xref_length()):
                try:
                    stream = pdf.extract_xref_stream(xref)
                    if b"%PDF" in stream:
                        # 打开嵌套的 PDF
                        nested_pdf = fitz.open("pdf", stream)
                        for nested_page_number in range(len(nested_pdf)):
                            nested_page = nested_pdf[nested_page_number]
                            # 提取嵌套 PDF 的图片
                            extract_regular_images(nested_page, page_number)
                            # 提取嵌套 PDF 中的表格
                            extract_tables(nested_page, page_number)
                except Exception as e:
                    continue

        # 遍历每一页
        for page_number in range(len(pdf)):
            page = pdf[page_number]
            # 提取普通图片
            extract_regular_images(page, page_number + 1)
            # 提取表格
            extract_tables(page, page_number + 1)
            # 提取嵌套 PDF 的图片
            # extract_nested_pdfs(page, page_number + 1)
            
        print(f"提取了 {len(images)} 个图片和表格")
        
        images = [self.convert_to_rgb_image(image["image_data"], image["ext"]) for image in images]
        # 保存图片帮助debug
        for i, image in enumerate(images):
            image.save(f"./cache/image_{i+1}.png")
            
        #通过通义千问判断这是否是一张表格或完整的图片
        def call_with_local_file(local_path):
            image_path = f"file://{local_path}"
            messages = [{'role': 'system',
                        'content': [{'text': '如果他是论文中的图表，请回答True，否则请回答False。不要输出其他内容，仅输出True或False'}]}, 
                        {'role':'user',
                        'content': [{'image': image_path},
                                    {'text': '这是一张图表么？如果是请回答True，否则请回答False。不要输出其他内容'}]}]
            response = MultiModalConversation.call(model='qwen-vl-plus', messages=messages)
            print(response)
            return str(response['output']['choices'][0]['message']['content'])
        final_images=[
        ]
        for i,image in enumerate(images):
            try:
                llm_judge = call_with_local_file(f"./cache/image_{i+1}.png").lower()
                if "true" in llm_judge or "yes" in llm_judge or "是" in llm_judge:
                    final_images.append(image)
                else:"不符合要求"
            except Exception as e:
                print("出现错误",e)
        print(f"经过VLM筛选提取了 {len(final_images)} 个图片和表格")
        for i, image in enumerate(final_images):
            image.save(f"./cache/a_final_image_{i+1}.png")
        return final_images

    def convert_to_rgb_image(self, image_bytes, image_ext):
        """Converts an image in bytes to an RGB image."""
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode != "RGB":
            image = image.convert("RGB")
        return image
