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
        "为论文讲解视频生成一个适合B站/小红书的中文标题。"
        "格式：「论文英文原名」+ 中文短语\n"
        "要求：\n"
        "1. 必须以论文英文原名开头（如 LeWorldModel、FlowDiffusion、SpatialVLA），后接英文冒号':'再写中文部分\n"
        "2. 中文部分15字以内，口语化，突出论文最酷的那个点\n"
        "3. 用通俗的方式表达（比如速度快了多少倍、效果好了多少、用了什么巧妙的思路）\n"
        "4. 禁止使用'首次'、'首个'、'突破'、'震撼'、'最新进展'、'颠覆'等夸张宣传词\n"
        "5. 好标题示例：'LeWorldModel: 只用两个损失就能预测世界'、'FlowDiffusion: 用光流让机器人动作更丝滑'\n"
        "仅输出标题，不加引号或其他内容。"
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


# ---- Manim 动画生成相关 Prompts ----

_MANIM_LAYOUT_RULES = (
    "\n\n【布局铁律 — 必须严格遵守】:\n"
    "1. Manim 默认画框：X 轴 [-7, 7]，Y 轴 [-4, 4]。所有元素必须在此范围内。\n"
    "2. 同一时刻屏幕上最多 5 个主要元素。超过时必须先 FadeOut 旧元素再展示新元素。\n"
    "3. 使用 .scale_to_fit_width() 或 .scale_to_fit_height() 确保元素不超框。\n"
    "4. 标题 font_size=28，正文 font_size=18-20，注释 font_size=14-16。公式 .scale(0.7-0.8)。禁止 scale_to_fit_width 超过 10。\n"
    "5. 元素间距至少 0.5 单位，用 buff=0.3 以上。\n"
    "6. 分步展示：每展示一组新内容前，FadeOut 上一组（标题可保留）。\n"
    "7. 禁止一次性展示超过 3 行公式/文字，必须分步骤。\n"
    "8. 中文文字不要指定 font 参数，让 Manim 使用系统默认字体。\n"
    "9. 整体动画时长控制在 15-25 秒。\n"
    "10. 【LaTeX 铁律】MathTex 禁止使用 substrings_to_isolate 参数，它会破坏括号匹配。\n"
    "11. 【LaTeX 铁律】禁止使用 set_color_by_tex()。如需高亮，用多个 MathTex 拼接或用 SurroundingRectangle。\n"
    "12. 【LaTeX 铁律】禁止使用 TransformMatchingTex。用 FadeOut + FadeIn 替代。\n"
    "13. 【LaTeX 铁律】\\left 和 \\right 必须成对出现，不能被拆分到不同的 MathTex 参数中。\n"
    "14. 【LaTeX 铁律】公式尽量写在一个完整字符串中，不要拆分成多个参数。\n"
)

prompts_dict["manim_analyze_script"] = (
    "你是一名学术动画专家。给定一篇论文的视频脚本（JSON 格式，含 opening/intro/method/results 段落）和论文原文，"
    "请分析脚本中哪些内容适合用 Manim 动画展示。\n"
    "需要识别以下类型：\n"
    "1. formula — 数学公式、损失函数、注意力机制等（从原文中提取对应的 LaTeX）\n"
    "2. architecture — 模型结构、网络层级（从原文中提取结构描述）\n"
    "3. flow — 算法步骤、数据流、pipeline\n"
    "4. title — 论文标题和关键结论\n"
    "5. results — 实验结果、性能数据、对比表格（必须包含，从原文 Results/Experiments 部分提取具体数字）\n\n"
    "返回严格 JSON 数组，每个元素格式：\n"
    '{"section": "method", "type": "formula", "script_excerpt": "脚本中对应的原文片段", '
    '"latex": "LaTeX公式（仅formula类型需要）", "description": "内容描述（要具体到论文的方法名称和细节，不要泛泛而谈）", "scene_name": "唯一的英文类名"}\n\n'
    "要求：\n"
    "- 至少提取 2 个场景，最多 5 个\n"
    "- formula 类型必须包含从原文提取的准确 LaTeX 公式\n"
    "- description 必须具体提到论文的方法名称、模块名称、独特之处，禁止使用通用描述\n"
    "- scene_name 必须是合法的 Python 类名\n"
    "- title 类型必须放在第一个位置（作为开场），results 类型必须放在最后一个位置（展示实验数据）\n"
    "- 必须包含至少一个 results 类型场景，展示论文的关键实验数据（如成功率、性能对比等）\n"
    "- 仅输出 JSON 数组，不要其他内容\n"
)

prompts_dict["manim_generate_formula"] = (
    "你是 ManimCE (Manim Community Edition) 专家。请生成一个展示数学公式推导的 Manim Scene。\n\n"
    "代码要求：\n"
    "1. 使用 `from manim import *`\n"
    "2. 类名使用提供的 scene_name\n"
    "3. 动画流程（分步展示，每步之间先清理上一步）：\n"
    "   - 第1步：显示公式标题（Text, font_size=28），停留1秒\n"
    "   - 第2步：FadeOut 标题，用 Write 展示主公式（MathTex, scale=0.9），停留2秒\n"
    "   - 第3步：用 Indicate 高亮公式中的关键变量，添加1-2个简短注释（Text, font_size=22），停留1.5秒\n"
    "   - 第4步：FadeOut 注释，如有推导步骤用 TransformMatchingTex 变换公式，停留2秒\n"
    "   - 第5步：FadeOut 所有元素\n"
    "4. 公式居中放置，注释放在公式下方\n"
    "5. 总共不超过 6 个 play() 调用\n"
    + _MANIM_LAYOUT_RULES +
    "仅输出完整的 Python 代码，不要 markdown 代码块标记，不要解释文字。\n"
)

prompts_dict["manim_generate_architecture"] = (
    "你是 ManimCE (Manim Community Edition) 专家。请生成一个展示模型架构的 Manim Scene。\n\n"
    "代码要求：\n"
    "1. 使用 `from manim import *`\n"
    "2. 类名使用提供的 scene_name\n"
    "3. 架构图设计：\n"
    "   - 每个模块用 Rectangle(width=2.5, height=0.8) + Text(font_size=20)\n"
    "   - 最多 4-5 个模块，从上到下或从左到右排列\n"
    "   - 用 Arrow(stroke_width=2, buff=0.15) 连接\n"
    "   - 不同模块用不同颜色（BLUE, GREEN, YELLOW, RED, PURPLE）\n"
    "4. 动画流程：\n"
    "   - 先显示标题，然后逐个 FadeIn 模块 + GrowArrow 连接\n"
    "   - 最后 Indicate 高亮核心模块\n"
    "   - 总共不超过 10 个 play() 调用\n"
    "5. 所有模块位置必须手动计算，确保不重叠、不超框\n"
    + _MANIM_LAYOUT_RULES +
    "仅输出完整的 Python 代码，不要 markdown 代码块标记，不要解释文字。\n"
)

prompts_dict["manim_generate_flow"] = (
    "你是 ManimCE (Manim Community Edition) 专家。请生成一个展示算法流程的 Manim Scene。\n\n"
    "代码要求：\n"
    "1. 使用 `from manim import *`\n"
    "2. 类名使用提供的 scene_name\n"
    "3. 流程图设计：\n"
    "   - 最多 5 个步骤节点，用 RoundedRectangle(width=2.5, height=0.7, corner_radius=0.15) + Text(font_size=18)\n"
    "   - 从左到右排列，或分两行排列（上行3个，下行2个）\n"
    "   - 用 Arrow(stroke_width=2, buff=0.15) 连接\n"
    "4. 动画流程：\n"
    "   - 显示标题，然后逐步 Create 节点 + GrowArrow\n"
    "   - 可选：用 Dot 沿路径移动表示数据流\n"
    "   - 总共不超过 10 个 play() 调用\n"
    "5. 整体布局用 VGroup 管理，用 .arrange() 或手动定位，确保不超框\n"
    + _MANIM_LAYOUT_RULES +
    "仅输出完整的 Python 代码，不要 markdown 代码块标记，不要解释文字。\n"
)

prompts_dict["manim_generate_title"] = (
    "你是 ManimCE (Manim Community Edition) 专家。请生成一个展示论文标题和核心贡献的 Manim Scene。\n\n"
    "代码要求：\n"
    "1. 使用 `from manim import *`\n"
    "2. 类名使用提供的 scene_name\n"
    "3. 展示内容：\n"
    "   - 论文标题（Text, font_size=32, color=BLUE），居中显示\n"
    "   - 1-3 个核心贡献点（Text, font_size=22），逐条出现在标题下方\n"
    "4. 动画流程：\n"
    "   - Write 标题 → Wait(1) → 逐条 FadeIn 贡献点 → Wait(2) → FadeOut 全部\n"
    "   - 总共不超过 8 个 play() 调用\n"
    "5. 所有文字居中排列，用 VGroup + arrange(DOWN, buff=0.5)\n"
    + _MANIM_LAYOUT_RULES +
    "仅输出完整的 Python 代码，不要 markdown 代码块标记，不要解释文字。\n"
)

prompts_dict["manim_generate_results"] = (
    "你是 ManimCE (Manim Community Edition) 专家。请生成一个展示论文实验结果的 Manim Scene。\n\n"
    "代码要求：\n"
    "1. 使用 `from manim import *`\n"
    "2. 类名使用提供的 scene_name\n"
    "3. 展示方式（用 Text 列表，禁止用 Rectangle 柱状图）：\n"
    "   - 标题 Text(font_size=28) 居中置顶\n"
    "   - 每条结果用 Text(font_size=22)，格式：任务名 ... 数值 (提升)\n"
    "   - 数值用 GREEN 高亮，提升百分比用 YELLOW\n"
    "   - 最后一行用 BOLD 显示平均值/总结\n"
    "   - 最多展示 6 条数据，超过的合并为平均值\n"
    "4. 动画：标题 Write → 逐条 FadeIn 数据 → 高亮平均值\n"
    "5. 最后保持内容在屏幕上，不要 FadeOut\n"
    "6. 数据必须从论文原文中提取真实数字，禁止编造\n"
    "7. 所有元素必须在 X[-7,7] Y[-4,4] 范围内，用 scale_to_fit_width(13) 确保不超框\n"
    + _MANIM_LAYOUT_RULES +
    "仅输出完整的 Python 代码，不要 markdown 代码块标记，不要解释文字。\n"
)
