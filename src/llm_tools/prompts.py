from src.config import OUTPUT_LANGUAGE

# 语言后缀
LANGUAGE_SUFFIX = {
    "zh": "\n请用中文回答。输出语言：中文",
    "en": "\nPlease answer in English. Output language: English"
}




prompts_dict = {
    #key 必须是和函数名相同
    "generate_summary": (
        "请总结以下论文的核心内容,重点讲解方法，参考摘要，请使用简洁的表达，生成约{word_budget}字的总结。"
        "禁止输出markdown形式的文本，不要一条一条的列出，而是以长文的形式。"
        "你的目标是帮助用户快速理解论文核心内容，语言通俗易懂，适合制作论文讲解视频的文案。"
        "请以 “这篇文章...”作为开始，不要重复文章标题\n"
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
        "为讲解视频生成一个简介易懂明了吸引人的中文标题，仅输出标题不输出其他内容，"
        "禁止输出多余内容，与标点符号，不要标题加引号。"
    ),
    "generate_origin_title": "论文的标题是什么？仅输出论文英文标题,不输出任何其他的文字",
    "generate_video_proceedings": (
        "请问这篇论文是发表在哪个会议或期刊上的？仅输出会议或期刊名称如ICRA2025，CVPR2024，不输出其他多余文字,"
        "如果文字中没有提到请输出Arxiv2025"
    ),
    "generate_structured_video_plan": (
        "你是一名严谨的学术视频脚本策划，请根据提供的论文正文（可能包含摘要、正文、实验）生成 JSON 结构化脚本。"
        "整体篇章需覆盖 4 个部分：0) opening，1) intro 背景与挑战，2) method 分模块讲解主图，3) results/impact。"
        "请严格输出 JSON，键包括："
        "opening: {\"script\": 用一段吸引人的开场白串联论文标题与亮点, \"visual_prompt\": 用于AI绘图的中文/英文提示词}；"
        "intro: {\"script\": 介绍研究背景与挑战，语气口语化, \"visual_prompt\": 用1-2句描述希望生成的概念性插画；}\n"
        "method: {\"overview\": 总体思路概述, \"modules\":[{\"name\": 模块名, \"description\": 20~40字说明}...], \"script\": 将overview与modules串成完整口播};"
        "results: {\"script\": 说明问题解决效果、实验结果与意义, \"evidence_points\": 列出2~3条关键指标或现象，用短句}."
        "语言要求：纯中文，禁止markdown/列表符号；JSON 中的字符串不要包含换行符或引号冲突；"
        "若缺少信息请基于已有文本保守推断，绝不虚构会议/数据。"
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
        "你是一名生动的学术讲师，负责为视频配音生成教学式图像讲解内容。"
        "始终返回严格可解析的JSON，字段包括：caption、detailed_explanation、key_points、qa、figure_role、recommended_section、main_figure_score。"
        "教学要求：1)语气生动活泼，像老师授课一样有感染力；2)前后内容有承接，过渡自然；3)逻辑清晰简洁，每句话只讲一个核心点；4)每张图片的讲解要分段进行，避免文字堆叠。"
        "caption 需为简洁描述；detailed_explanation 是分段式讲解内容，每段1-2句话，语气像老师在课堂上引导学生，句子短、适合朗读，不使用 Markdown、列表或公式；"
        "注意：每句话必须控制在30字以内！每张图片的详细讲解总长度不超过{per_image_budget}字！"
        "key_points 为3到5条自然语言短句组成的列表，不加序号或符号；qa 为3个对象，每个对象含 question 和 answer，聚焦图像内容与全文关联，不猜测会议或投稿信息；"
        "figure_role 用一句话说明该图更像总览、方法流程、实验对比或其他；recommended_section 需在 opening/intro、method、results、other 中选择最合适的章节；"
        "main_figure_score 为0到1之间的小数，表示该图是否可能是论文主图/总览图，提供保守估计。"
        "除非缺少信息，不要输出 '未知'，若信息不足请明确说明。"
    ),
    "explain_image_user": (
        "请结合图像内容生成教学式讲解，语言生动有趣，像老师在课堂上引导学生思考。"
        "讲解要基于文章全部内容，理解图像在论文中的作用和位置，前后内容要有逻辑承接。"
        "每张图片的详细讲解要分段输出，每段1-2句话，每句话必须在30字以内！"
        "严格控制总长度：每张图片的详细讲解（detailed_explanation）总字数不超过{per_image_budget}字！"
        "如果提供图像题注，请结合题注内容进行讲解。"
        "返回的JSON键为 caption、detailed_explanation、key_points、qa、figure_role、recommended_section、main_figure_score。"
        "recommended_section 只允许 opening/intro、method、results、other 四种取值；"
        "main_figure_score 必须为0~1的小数。"
        "key_points 需给出3到5条短句，qa 给出3组问答，均使用自然教学口语，避免列表符号。"
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