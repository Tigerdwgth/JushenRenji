from src.config import OUTPUT_LANGUAGE

# 语言后缀
LANGUAGE_SUFFIX = {
    "zh": "\n请用中文回答。输出语言：中文",
    "en": "\nPlease answer in English. Output language: English"
}




prompts_dict = {
    #key 必须是和函数名相同
    "generate_summary": (
        "你是一名科技视频讲师，请将论文转化为一段引人入胜的视频讲稿，约{word_budget}字。"
        "请按以下叙事结构组织：\n"
        "1. 开场Hook（约5%）：用一句话点出这篇论文解决的'痛点'或令人惊叹的成果，激发好奇心。\n"
        "2. 背景铺垫（约15%）：为什么这个问题重要？前人做到了什么程度？\n"
        "3. 核心方法（约50%）：这篇论文的创新在哪里？请用类比或通俗比喻帮助理解，逐步拆解。\n"
        "4. 实验亮点（约20%）：关键实验结果是什么？比之前好了多少？\n"
        "5. 总结展望（约10%）：这项工作的意义是什么？未来还能怎么做？\n"
        "写作要求：语气自然口语化，像老师给学生讲课；用'首先'、'接下来'、'最后'等连接词过渡；"
        "禁止markdown/列表/公式符号；禁止复读论文标题；以'大家好'或'今天'开场。\n"
    ),
    "generate_short_summary": (
        "你现在是组会分享论文的研究生，请分享下面的文章，严格遵循以下要求。"
        "1.简单介绍一下文章工作单位（使用缩写），不用说明作者名字，"
        "2. 如果有提到是什么会议也请说明（仅使用缩写+年份形式）,没有提及的话，请直接忽略这个要求，不用说未提及，请勿编造任何信息。"
        "3. 用两句话简短介绍一下这篇文章的核心方法、模型结构和贡献，言简意赅。"
        "4. 禁止复读论文标题"
        "5. 禁止使用markdown形式的输出，请用完整的句子，而非列举点,使用中文"
        "6. 严格控制总字数在{word_budget}字以内"
    ),
    "generate_video_title": (
        "为论文讲解视频生成一个吸引人的中文标题。"
        "要求：简洁有力（15字以内）；突出核心亮点或创新；可包含'首次'、'突破'、'新方法'等关键词；"
        "仅输出标题，不加引号、标点或其他内容。"
    ),
    "generate_origin_title": "论文的标题是什么？仅输出论文英文标题,不输出任何其他的文字",
    "generate_video_proceedings": (
        "请问这篇论文是发表在哪个会议或期刊上的？仅输出会议或期刊名称如ICRA2025，CVPR2024，不输出其他多余文字,"
        "如果文字中没有提到请输出Arxiv2025"
    ),
    "generate_structured_video_plan": (
        "你是一名顶级科技视频脚本策划。请根据论文内容生成严格的 JSON 结构化脚本。"
        "覆盖 4 个部分：opening、intro、method、results。\n"
        "输出格式示例：\n"
        "{\"opening\": {\"script\": \"大家好！今天要讲的这篇论文非常有意思...\"},"
        " \"intro\": {\"script\": \"要理解这项工作，我们首先要知道...\"},"
        " \"method\": {\"script\": \"这篇论文提出的核心方法是...\"},"
        " \"results\": {\"script\": \"实验结果表明...\"}}\n"
        "写作要求：\n"
        "1. opening（约5%）：用一句令人好奇的问题或惊人数据开场，然后引出论文主题。\n"
        "2. intro（约15%）：讲清楚问题背景，为什么难，前人怎么做的。\n"
        "3. method（约50%）：拆解核心方法，用类比和通俗语言，像老师教学生。\n"
        "4. results（约30%）：关键实验结果 + 这项工作的意义和启发。\n"
        "全部使用中文口语，禁止markdown/列表/公式，禁止虚构数据。仅输出JSON。"
    ),
    "get_paper_demo_website": (
        "请问这篇论文的视频网址是什么？,请以json格式输出,需要可以被python解析,禁止输出其他多余文字，禁止输出markdown，"
        "仅输出最终json,格式：{\"state\":\"0/1之间的一个代表失败或成功\",\"url\":\"http://www.proj-demo.com\"}"
    ),
    "get_captions_from_page": (
        "请从以下文本中提取图片和表格的题注,题注可能是英文或者还是中文的，比如fig，table等，"
        "要求提取图片题注和表格题注，分别放在两个列表中，"
        "返回格式为[[图片题注1,图片题注2...],[表格题注1,表格题注2...]]，"
        "如果没有图片或表格题注，则对应的列表为空。"
        "禁止输出markdown形式的文本，禁止输出多余内容，"
        "禁止输出其他格式的文本，禁止输出其他内容。"
        "请确保提取的题注是完整的句子，"
        "如果题注中包含图片或表格的编号，请保留编号。"
    ),
    "extract_captions_to_dict": (
        "请从以下文本中提取图片和表格的题注，返回JSON字典格式。按照正文中的顺序进行输出"
        "要求："
        "1. 识别所有图片题注（Figure, Fig, 图等）和表格题注（Table, Tab, 表等）"
        "2. 为每个题注分配唯一的键值：图片用fig_1, fig_2...，表格用tab_1, tab_2..."
        "3. 值为完整的题注文本，保留编号和描述"
        "4. 仅输出JSON格式，不要其他内容"
        "5. 如果没有找到题注，返回空字典{}"
        "示例输出格式：{\"fig_1\": \"Figure 1: Network architecture\", \"tab_1\": \"Table 1: Experimental results\"}"
    ),
    "add_context_to_image_explanations": (
        "你是学术视频脚本编辑，需要为一系列图像解释添加上下文和过渡语句。"
        "给定一组图像解释，请为每个解释添加："
        "1. context: 说明这张图属于论文的哪个部分（introduction/motivation/method/experiment/results/conclusion），用一句话简洁描述"
        "2. transition: 从前一张图片到这张图片的过渡语句，用一句话自然连接上下文"
        "3. role: 这张图在论文中的作用（overview/method/result/comparison等）"
        "请保持原有的detailed_explanation不变，只是添加context和transition。"
        "请返回JSON数组，数组长度与输入相同，每个元素包含原有的所有字段，并添加context、transition、role字段。"
        "请用中文回答。输出语言：中文"
    ),
    # Image Agent Prompts
    "explain_image_system": (
        "你是一名优秀的学术讲师，像在课堂上指着图表给学生讲解。"
        "始终返回严格可解析的JSON，字段：caption、detailed_explanation、key_points、qa、figure_role、recommended_section、main_figure_score。"
        "讲解风格：1)语气生动有感染力，像老师对学生说话；2)先说'我们来看这张图'引入；"
        "3)解释图中X轴Y轴代表什么、关键曲线/模块是什么；4)总结这张图说明了什么。"
        "caption 为一句话描述；detailed_explanation 是连贯的讲解段落，适合朗读，不使用Markdown/列表/公式；"
        "总长度不超过{per_image_budget}字。"
        "key_points 为3-5条自然语言短句；qa 为3组问答；"
        "figure_role 说明该图是总览/方法/实验/对比中的哪种；"
        "recommended_section 在 opening/intro、method、results、other 中选一；"
        "main_figure_score 为0~1的小数。不要输出'未知'。"
    ),
    "explain_image_user": (
        "请结合图像和论文全文内容生成讲解，像老师在黑板前指着图表讲课。"
        "结构：1)引入这张图——它在论文哪个部分、承接什么内容；"
        "2)快速解读——图中关键元素代表什么；"
        "3)核心洞察——这个结果/结构说明了什么，为什么重要。"
        "总字数不超过{per_image_budget}字。如果有图像题注请结合使用。"
        "返回JSON，键：caption、detailed_explanation、key_points、qa、figure_role、recommended_section、main_figure_score。"
        "recommended_section 仅允许 opening/intro、method、results、other；main_figure_score 为0~1小数。"
    ),
    "explain_image_ocr_fallback": (
        "你是学术论文图像解读专家。请基于题注、论文摘要、全文内容和OCR文本，生成教学式讲解内容，返回JSON，字段：caption, detailed_explanation, key_points, qa。"
        "讲解语气要生动有趣，像老师在课堂上引导学生思考，前后内容要有逻辑承接，每段文字要简洁明了。"
    ),
    "rate_image_importance": (
        "你是学术论文分析专家。给定一组图片的题注/描述，请对每张图片的重要性打分（1-10分）。"
        "重要性标准：总览图/方法架构图 > 核心实验结果图 > 消融实验图 > 其他辅助图。"
        "请严格返回JSON格式：{\"scores\": [分数1, 分数2, ...]}，分数列表长度必须与输入数量一致。"
        "禁止输出其他内容。"
    ),
}
def get_language_suffix():
    """获取当前语言的后缀"""
    return LANGUAGE_SUFFIX.get(OUTPUT_LANGUAGE, LANGUAGE_SUFFIX["zh"])

# 在每个提示词后添加语言后缀
def add_language_suffix_to_prompts():
    """为所有提示词添加语言后缀"""
    suffix = get_language_suffix()
    for key in prompts_dict:
        prompts_dict[key] = prompts_dict[key] + suffix


# 初始化提示词语言后缀
add_language_suffix_to_prompts()