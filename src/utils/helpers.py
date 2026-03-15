def generate_summary(text):
    # 这里可以实现一个简单的文本摘要生成逻辑
    # 例如，提取文本的前几句话作为摘要
    sentences = text.split('. ')
    summary = '. '.join(sentences[:2]) + '.' if sentences else ''
    return summary

def create_title(pdf_title):
    # 生成引人注目的标题
    # 可以在标题前添加一些描述性词语
    return f"深入解析：{pdf_title}"