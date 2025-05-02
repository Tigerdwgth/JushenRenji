from PIL import Image, ImageDraw, ImageFont

def generate_cover(cover_pic, cover_title, output_path="./pic/cover.png"):
    """
    输入图片路径与标题，生成封面图片
    生成封面图片，保存到指定目录
    Args:
        cover_pic (str): 封面背景图片路径
        cover_title (str): 封面标题
        output_path (str): 生成的封面图片保存路径
    """
    try:
        # 打开背景图片
        background = Image.open(cover_pic)
        cover_title ="\n".join([cover_title[i:i+10] for i in range(0, len(cover_title), 10)])  # 每行最多10个字
        
        # 调整图片大小到 1200x900
        target_size = (1200, 900)
        background = background.resize(target_size)
        
        # 创建绘图对象
        draw = ImageDraw.Draw(background)
        
        # 设置字体（需要确保字体文件路径正确）
        font_path = r"F:\PaperReadingAgent\font\SIMHEI.TTF"  # 替换为实际字体路径
        font_size = 90
        font = ImageFont.truetype(font_path, font_size)
        
        # 获取图片尺寸
        img_width, img_height = background.size
        
        # 计算标题位置（居中）
        text_bbox = draw.textbbox((0, 0), cover_title, font=font)  # 获取文本边界框
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        text_x = (img_width - text_width) // 2
        text_y = (img_height - text_height) // 2  # 垂直居中
        
        # 绘制黑色边框（通过多次偏移绘制实现）
        outline_color = "black"
        for offset in [(-2, -2), (-2, 2), (2, -2), (2, 2), (0, -2), (0, 2), (-2, 0), (2, 0)]:
            draw.text((text_x + offset[0], text_y + offset[1]), cover_title, font=font, fill=outline_color)
        
        # 绘制黄色文字
        draw.text((text_x, text_y), cover_title, fill="yellow", font=font)
        
        # 保存生成的封面图片
        background.save(output_path)
        print(f"封面图片已成功保存到: {output_path}")
    except Exception as e:
        print(f"生成封面图片时出错: {e}")

if __name__ == "__main__":
    # 示例
    cover_pic = r"F:\PaperReadingAgent\output\daily_summary.png"
    cover_title = "封面上传功能测sfsfsdfsdfsdfs试"
    output_path = r"F:\PaperReadingAgent\output\cover.png"
    generate_cover(cover_pic, cover_title, output_path)