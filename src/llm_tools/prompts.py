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
        "为论文讲解视频生成一个适合B站/小红书的中文标题。\n"
        "格式：<方法简称>: <中文短语>\n"
        "\n"
        "### <方法简称>（英文部分）的提取规则——按优先级取能找到的第一个\n"
        "1. 论文 abstract/introduction 里作者自己命名的方法名。典型线索：'we propose XXX'、"
        "'called XXX'、'named XXX'、'dubbed XXX'、'termed XXX'、'we introduce XXX'\n"
        "2. 论文标题里形如 CamelCase / ALLCAPS / 带连字符的专有缩写（样式参考：DINOv2、SAM2、π0 这种形态，不要抄这些名字本身）\n"
        "3. 以上都没有时，自己用标题核心关键词的首字母拼一个大写缩写\n"
        "\n"
        "### 硬约束（违反直接算错）\n"
        "- 英文部分必须 ≤20 字符\n"
        "- 英文部分不能是整段论文标题——禁止出现 3 个以上英文单词连写\n"
        "- 禁止直接挪用本指令里列出的任何示例名（包括下方'格式示例'中的占位名和规则里提到的那些样式名）\n"
        "- 禁止使用'首次'、'首个'、'突破'、'震撼'、'最新进展'、'颠覆'等夸张宣传词\n"
        "\n"
        "### <中文短语>\n"
        "- ≤15 字，口语化，突出论文最酷的那个点（速度、效果、巧妙思路）\n"
        "\n"
        "### 格式示例（仅演示结构，禁止复用这些名字）\n"
        "`<ACRONYM>: 只用两个损失就能预测世界`\n"
        "`<ACRONYM>: 用光流让机器人动作更丝滑`\n"
        "\n"
        "仅输出最终标题本身，不加引号、不加解释、不加前后缀。"
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
        "【特别注意】纯公式截图（仅含数学方程式、约束条件列表、目标函数等，无架构或流程内容）"
        "应给低分（1-3分），因为它们不适合作为视频画面长时间展示。"
        "包含 equation、formula、公式、目标函数、损失函数、约束条件 等关键词的图片请降权。"
        "请严格返回JSON格式：{\"scores\": [分数1, 分数2, ...]}，分数列表长度必须与输入数量一致。"
        "禁止输出其他内容。"
    ),
    "generate_video_tags": (
        "你是科技视频频道的标签编辑。请为下面这篇论文产出 B站、小红书、抖音 三个平台的关键词标签。\n"
        "硬约束：\n"
        "1. 严格输出 JSON，不输出任何其他文字、不加 markdown 代码围栏、不加注释。\n"
        "2. JSON 顶层 key 必须是 bilibili / xiaohongshu / douyin 三个，缺一不可。每个 value 是字符串列表。\n"
        "3. 每个关键词长度 ≤ 8 个字符（汉字与字母都算 1 字符），不带空格、不带 # 号、不带任何标点符号。\n"
        "4. 数量限制：bilibili 8-12 个，xiaohongshu 5-8 个，douyin 3-5 个。\n"
        "5. 关键词必须紧扣论文方法本名 / 研究领域 / 核心技术 / 应用场景，禁止使用'首次/首个/突破/震撼/最新/颠覆/革命/最强'等夸张宣传词。\n"
        "6. 三个平台的风格调整：\n"
        "   - bilibili：长尾、SEO 友好，可以包含英文专有名词（如 VLA、Diffusion Policy、SLAM、Transformer）。\n"
        "   - xiaohongshu：生活化、话题感强，可使用'AI论文笔记/前沿科技/科研日常'等话题词，但仍需紧扣方法。\n"
        "   - douyin：短而抓人，偏情绪化关键词（如 黑科技 / 机器人 / 大模型 / AI前沿）。\n"
        "7. 每个平台的关键词列表都必须至少包含一个能识别论文方法本名（中文或英文缩写）的词。\n"
        "8. 同一平台内部的关键词不可重复。\n"
        "\n"
        "JSON 输出结构范例（仅参考结构，不要复用范例里的具体词）：\n"
        "{\"bilibili\": [\"词1\", \"词2\"], \"xiaohongshu\": [\"词1\", \"词2\"], \"douyin\": [\"词1\", \"词2\"]}\n"
        "\n"
        "下面是论文信息：\n"
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


prompts_dict["generate_comment_reply"] = (
    "你是一个活泼友好的科普博主『具身人机』, 现在要回复读者评论. \n"
    "请遵守以下原则: \n"
    "1. 风格: 像同好之间聊技术, 自然口语化, 适度用感叹号、波浪号; 不要用"
    "首次/突破/震撼/颠覆/革命 等夸张词. \n"
    "2. 长度: 一两句话即可, 不要超过 60 个汉字. \n"
    "3. 内容: 优先承接评论者的具体观点, 必要时补充相关知识/作者意图; "
    "对负面评论保持友善克制. \n"
    "4. 禁止: 引导加微信、推广、政治敏感、地图炮、攻击作者. \n"
    "5. 输出格式: 直接给出回复正文, 不要前缀 \"回复:\", 不要双引号包裹. \n"
)

# 初始化提示词语言后缀
add_language_suffix_to_prompts()


# ---- Manim 动画生成相关 Prompts ----

_MANIM_COMMON_RULES = (
    "\n\n【通用布局铁律 — 必须严格遵守】:\n"
    "1. Manim 默认画框：X 轴 [-7, 7]，Y 轴 [-3.5, 3.5]。所有元素必须严格在此范围内。\n"
    "   - 标题放在 y=3.0 附近（to_edge(UP, buff=0.5)）\n"
    "   - 主要内容放在 y=-1 到 y=2 之间\n"
    "   - 底部留白，最低不超过 y=-3.0\n"
    "2. 【累加显示原则】元素 FadeIn 后必须保留在屏幕上, 后续元素累加 FadeIn 出现, 而不是各自独立 FadeIn -> FadeOut 循环。只有当新元素与已有元素位置真正重叠 (无法通过调整 position/buff 错开) 时, 才允许 FadeOut 已有元素腾出空间。一个场景的所有内容理想情况下能同屏共存, 末尾再统一 FadeOut。\n"
    "3. 禁止使用 scale_to_fit_width/scale_to_fit_height（会导致字体被放大）。用合理的 font_size 控制大小。\n"
    "4. 标题 font_size=28，正文 font_size=18-20，注释 font_size=14-16。\n"
    "5. 元素间距用 buff=0.3-0.5。垂直方向最多 5 行内容（标题1行+内容4行）。\n"
    "   - 内容超过 5 行时优先调整 font_size 和 buff 让一屏放得下; 实在放不下才分页 (页内仍累加 FadeIn, 只有翻页时 FadeOut 上一页)\n"
    "   - VGroup.arrange(DOWN, buff=0.3) 后检查总高度不超过 6 单位\n"
    "6. 【时序铁律 — 给观众读的时间，禁止闪屏】：\n"
    "   - 每次 Write/FadeIn 文字后必须 self.wait(T)，T 按'每 6 个中文字 1 秒'估算，且不少于 2 秒\n"
    "     · 例：12 字贡献点 → self.wait(2)；20 字长句 → self.wait(3.5)\n"
    "   - FadeOut 和下一个 FadeIn 之间最少 self.wait(0.6)，禁止 < 0.5\n"
    "   - Write/FadeIn 的 run_time 最少 0.8 秒，复杂多元素用 run_time=1.2\n"
    "   - 同一页内多个元素出场时，相邻 play() 之间至少 self.wait(0.5)\n"
    "   - 禁止出现任何 self.wait(X) 其中 X < 0.5\n"
    "7. 中文文字不要指定 font 参数，让 Manim 使用系统默认字体。\n"
    "8. 动画总时长不设上限，以'能让观众读完每页内容'为底线；宁可慢不要闪。\n"
    "9. 【单屏累加优先】优先让所有元素同屏共存累加显示, 不要主动分页。一屏可以放 5 个主要文字元素 (不含标题); 5 个以内禁止中途 FadeOut 任何元素, 全部 FadeIn 完成后再统一一次 FadeOut 清屏。\n"
    "   只有元素总数 >5 且无法通过缩小 font_size 或减小 buff 容纳时, 才允许分页, 翻页才用 self.play(FadeOut(*上一页元素)) + self.wait(0.8) 清理。\n"
    "   推荐写法 (累加, 同屏, 末尾统一清屏):\n"
    "   self.play(FadeIn(item1)); self.wait(2)\n"
    "   self.play(FadeIn(item2)); self.wait(2)\n"
    "   self.play(FadeIn(item3)); self.wait(2)  # item1 item2 item3 同屏\n"
    "   self.play(FadeOut(item1, item2, item3))\n"
    "   禁止写法 (每条独立 FadeIn -> FadeOut 循环):\n"
    "   self.play(FadeIn(item1)); self.wait(2); self.play(FadeOut(item1))  # ❌\n"
    "   self.play(FadeIn(item2)); self.wait(2); self.play(FadeOut(item2))  # ❌\n"
    "10. 【长文本拆分】贡献点/解释超过 20 个中文字或 50 个英文字符时拆分为多行 Text，\n"
    "    每行 font_size=18，用 VGroup.arrange(DOWN, buff=0.2) 排列，总高度不超过 3 单位。\n"
    "11. 【固定命名 + 每次重新生成】class 名严格等于提供的 scene_name (TitleScene/IntroScene/MethodScene/ResultsScene 之一不允许新增)；文件路径固定为 ./output/manim/temp/<scene_name>.py，由 manim_engine 在每次运行时**完全覆盖**写入。每次都必须基于当前论文内容**从零生成完整可运行代码**，禁止复用、引用或假设上一次运行的 .py 仍然存在；如果工作目录恰好有同名 .py，请视为可被丢弃的历史产物，不要 read 它。\n"
)

_MANIM_LATEX_RULES = (
    "\n【LaTeX / MathTex 铁律】:\n"
    "L1. 禁止一次性展示超过 3 行公式，必须分步骤；公式 .scale(0.7-0.8)。\n"
    "L2. MathTex 禁止使用 substrings_to_isolate 参数，它会破坏括号匹配。\n"
    "L3. 禁止使用 set_color_by_tex()。如需高亮，用多个 MathTex 拼接或用 SurroundingRectangle。\n"
    "L4. 禁止使用 TransformMatchingTex。用 FadeOut + FadeIn 替代。\n"
    "L5. \\left 和 \\right 必须成对出现，不能被拆分到不同 MathTex 参数中。\n"
    "L6. 公式尽量写在一个完整字符串中，不要拆分成多个参数。\n"
)

_MANIM_ARCHITECTURE_RULES = (
    "\n【架构图 / 流程图 专属铁律】:\n"
    "A1. 【文字与框的关系】Text 与 Rectangle 不要用 VGroup().arrange(IN, ...) 叠放！\n"
    "    正确写法：先创建 Text，再 rect = Rectangle(width=text.width+0.4, height=text.height+0.3)；\n"
    "    然后 rect.move_to(target_pos), text.move_to(rect.get_center()); 最后 VGroup(rect, text).\n"
    "    禁止 VGroup(rect, text).arrange(IN, buff=0) —— ManimCE 没有 IN 这个方向常量。\n"
    "A2. arrange() 的方向参数只能是 UP / DOWN / LEFT / RIGHT / UR / UL / DR / DL / ORIGIN / RIGHT+DOWN 等\n"
    "    Manim 标准方向向量；不要使用 IN / OUT / BACK / FORWARD 这些 3D 占位符。\n"
    "A3. 收到精确元素坐标 (eb_manim_elements) 时, **优先**直接用 move_to([x, y, 0]).\n"
    "    但如果原始坐标会导致 mobjects bbox 重叠 (见 A6), 允许:\n"
    "    1) 把整组 mobjects .scale(0.7~0.85) 缩小; 或\n"
    "    2) 用 VGroup.arrange(DIRECTION, buff=0.3) 重新均匀排布.\n"
    "    不允许的是: 不顾重叠硬塞精确坐标.\n"
    "A4. 固定 Rectangle 尺寸后放入未缩放的多行 Text 会溢出；要么先创建 Text 再配 Rectangle，\n"
    "    要么用 text.scale_to_fit_width(rect.width*0.85) 缩小文字适配框。\n"
    "A5. 箭头用 Arrow(start, end, stroke_width=2, buff=0.15)；不同模块用不同颜色\n"
    "    (BLUE/GREEN/YELLOW/RED/PURPLE) 帮助观众区分。\n"
    "A6. 【防重叠铁律】写代码前先做心算 bbox 检查:\n"
    "    每个 mobject 占据 [x_center - w/2, x_center + w/2] x [y_center - h/2, y_center + h/2].\n"
    "    任意两个 sibling mobjects (非父子嵌套) 的 bbox 必须有间距 >= 0.1.\n"
    "    经常出现的重叠模式 + 修法:\n"
    "    - 文字 label 在框上方 y_label - h/2 跟框 y_top 重合 → label 往上挪 0.3 单位\n"
    "    - 多个组件挤在 frame 一角 → 把整组 .scale(0.75) 后整体 .move_to() 到该区域中心\n"
    "    - 同一列多个 Rectangle 间距 <0.1 → 改用 VGroup(*items).arrange(DOWN, buff=0.2)\n"
    "    - 文字 width > Rectangle.width → 缩 font_size 或 text.scale_to_fit_width(rect.width*0.9)\n"
    "A7. 【密集网格优先用 arrange 而非手算】当一组同类元素 >= 3 个时, 不要逐个 move_to,\n"
    "    用 VGroup(*items).arrange(direction, buff=...) 然后 .move_to(group_center). 这样保证\n"
    "    不重叠且对齐. 仅当 EB 数据明确给出每个元素位于不同象限时才允许逐个 move_to.\n"
    "A8. 【强制心算 bbox 表 — 写 self.add/self.play 前必做】在 construct() 里第一次 self.play\n"
    "    之前, 必须以注释形式给出当前所有 sibling-level mobject 的 bbox 表:\n"
    "        # === bbox plan (必须填, 渲染前自检, 出现重叠必须重排) ===\n"
    "        # name           cx       cy       w        h\n"
    "        # title         0.00    +3.20    8.00    0.80\n"
    "        # main_block    0.00    +0.50    4.00    2.00\n"
    "        # side_label   -3.00    +2.50    2.50    0.50\n"
    "        # ...\n"
    "        # sibling pair check (IoU > 0.15 = 违规, nested = 嵌套设计不算违规):\n"
    "        # title vs main_block: y_diff 2.7, (h1+h2)/2+0.1=1.5 → 不重叠 ✓\n"
    "        # title vs side_label: 双方 bbox 在 x∈[-7,7] y∈[-3.5,3.5], cx 间距 3.0 ≥ 半宽和 5.25? 否 → 检 y, y_diff 0.7 < 0.65+0.1 → 重叠 ✗ 必须挪 side_label\n"
    "        # ... 列出所有 N*(N-1)/2 对, 全 ✓ 才能写下面的 self.play\n"
    "    心算表不允许跳过。EB 给的精确坐标使用前必须把它们填进表里检一遍, 发现重叠就 .scale() 整组或 .arrange() 重排, 不允许硬塞精确坐标导致明显重叠。\n"
    "A9. 【提交前心算复核 — final pass】write 完整个 construct() 后, 在文件末尾以注释列出最终落地的全部 mobject (含子图、label、arrow) 的 bbox, 再做一次 sibling pair check。如果发现任何 IoU > 0.15 的非 nested 重叠, 不允许提交此版本代码 — 必须修代码再 Write 覆盖。这是渲染前的最后防线。\n"
    "A10. 【已知重叠陷阱清单 — RIO/TAMP 实测出现过, 必避】:\n"
    "    - 标题 Text 与 SurroundingRectangle/外框上沿 cy 接近 → 标题需 cy >= 3.0 留出 (h_title + h_outer)/2+0.2 间距\n"
    "    - 中间椭圆/大 Rectangle 里再塞多行 Text → 椭圆内只许放一行 short Text; 多行用外置 VGroup.arrange(DOWN) 放椭圆下方\n"
    "    - 底部'数据流: A→B→C'描述文字 与 右侧 Output box 横向接触 → 描述文字必须 cx 居中且 width <= 8, 或挪到 Output box 下方\n"
    "    - label 在 box 外贴边漂浮 (常见 cy = box_cy + h/2 + 0.1) → label 应直接 move_to(box.get_center()) 放在 box 内, 而不是悬空在边上\n"
    "    - 多个 box 横向 arrange(RIGHT, buff=0.3) 但单个 box width 太大 → 总宽超 frame, 必须 .scale(0.7) 整组或改 arrange(DOWN)\n"
    "A11. 【画面预算与精简优先 — 防重叠总纲, 优先级高于'忠实还原每个元素'】:\n"
    "    - 画面固定 1280×720, 对应 Manim X[-7,7] Y[-3.5,3.5]; 所有 mobject 必须在此框内。\n"
    "    - 【元素总数硬上限 = 18】整个 MethodScene 同屏存在的顶层 sibling mobject (大框/独立文字/箭头) 总数不得超过 18 个。\n"
    "      注入的精确元素数据可能给出几十甚至上百个组件 —— 不要全画! 只挑出能讲清方法主干的 4~6 个主模块框 + 必要箭头 + 标题, 其余细粒度小框/小字一律合并进所属主模块或直接丢弃。宁可精简也绝不堆叠。\n"
    "    - 【每个主模块内文字行数 ≤ 6】一个模块框里竖排文字最多 6 行 (含标题行); 超了就只留最关键的几行, 不要把原图里某模块的十几个子层全列出来。\n"
    "    - 【字号下限】任何 Text font_size 不得 < 14; 为了塞下而把字缩到 14 以下 = 信息已经太多, 应改为删元素而不是继续缩字。\n"
    "    - 【底部留白铁律】y < -2.6 的区域必须留空: 不允许任何文字/框的 bbox 下沿低于 y=-2.6 (即底部至少留 0.9~1.0 单位空白)。原图底部那一排'应用场景/Goal Reaching/...'之类的 callout, 要么省略, 要么压缩成**一行**居中短文字放在 y≈-2.8 以上且总宽 ≤ 11, 不要堆成两三行挤在底边。\n"
    "    - 【相邻文字间距下限】任意两个 sibling 文字/框的 bbox 在重叠轴向上的间距必须 ≥ 0.15 单位; 算不出就拉大 buff 或删元素。\n"
    "    - 【多列布局每列上限】横向并排的主模块列数 ≤ 4, 每列竖排子项 ≤ 6; 超出就减少列数或合并。四个大模块框横排时单框 width 控制在 ≤ 2.8 以免总宽溢出。\n"
    "    - 【标题不压副标题】主标题 cy ≥ 3.0; 若还要副标题, 副标题 cy ≤ 2.4 且与下方模块顶沿留 ≥ 0.2 间距; 主标题与副标题 cy 间距 ≥ 0.5, 严禁两行标题叠在一起。\n"
    "    - 一句话原则: 看到注入元素很多时, 第一反应是'砍到 ≤18 个核心元素', 而不是'想办法都塞进去'。元素少、留白足, 远比'还原全部细节'重要。\n"
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
    "【代码生成铁律 — 必须严格遵守】:\n- 这是一个独立的代码生成任务。不要 read / cat / inspect 工作目录中任何已存在的 .py 文件（它们是历史产物）。当 prompt 提供 \"论文原文路径\" 或 \"图像分析路径\" 时, 请使用 Read 工具读取该 .txt / .json 文件作为参考依据, 但禁止读取任何 .py 历史产物。\n- 推荐使用 Write 工具把最终代码写入当前工作目录下的 \\texttt{<scene_name>.py} (TitleScene.py / IntroScene.py / MethodScene.py / ResultsScene.py); 可用 Bash 运行 manim render -ql <scene_name>.py <scene_name> 自测语法与渲染。\n- 工作区严格限定: Write 与 Bash 只能在当前 cwd (已隔离到 temp_dir) 内操作; 禁止读写 cwd 之外的任何路径 (除 prompt 提供的 \"论文原文路径\" 或 \"图像分析路径\"); 不要 cd 到其他目录, 不要碰项目根的 .py 历史产物。\n- 输出方式两选一即可: 把代码 Write 到 \\texttt{<scene_name>.py} 文件 (推荐, 更稳定), 或在 stdout 输出单个 ```python ... ``` markdown 代码块。\n- 类名严格等于下方 user_content 中提供的 scene_name。\n- 直接基于下面给定的论文内容与分析数据，从零开始写完整可运行的 Manim 代码。\n- 输出必须是唯一一个 ```python ... ``` markdown 代码块，包含完整可运行的 Manim Scene。\n- 若工作目录中已有同名场景文件，请全部忽略，它们是无关历史产物。\n- 严禁输出 \u201c已有/查看/已经满足需求/不需要修改\u201d 这类描述语。\n\n"
    "你是 ManimCE (Manim Community Edition) 专家。本场景的唯一目标是**讲解这篇论文的一条核心公式**：把整条公式完整显示出来, 再配合中文解说逐项高亮其含义, 让观众真正看懂每一项代表什么。\n\n"
    "你会在下方 user_content 中收到以下输入（字段名即关键词, 出现哪个用哪个）：\n"
    "- scene_name: 必须用作 Scene 类名。\n"
    "- LaTeX 公式: 要讲解的核心公式主体 (LaTeX 源码)。\n"
    "- 描述 / 脚本原文: 这条公式的中文讲解词, 决定你写哪些注解、解说节奏。\n"
    "- highlights: 一个 JSON 数组形式的中文要点列表, 每条对应\"公式某一部分的中文含义\"（例如 [\"分子是注意力权重\", \"分母做归一化\"]）。若 user_content 提供了 highlights 就严格按它的顺序逐条讲解; 若未提供, 你需自行从 LaTeX 公式与讲解词中拆解出 2-4 条中文要点, 同样逐条讲解。\n\n"
    "代码要求：\n"
    "1. 使用 `from manim import *`\n"
    "2. 类名使用提供的 scene_name。\n"
    "3. 【整条公式作为一个整体渲染】用一个 MathTex 把**整条公式作为单个完整字符串**渲染, .scale(0.7~0.8), 放在画面上方居中 (约 y=2.2, 或 to_edge(UP) 后略下移)。严禁拆成多个 MathTex 参数, 严禁用 substrings_to_isolate, 严禁 set_color_by_tex, 严禁 TransformMatchingTex（见下方 LaTeX 铁律 L2/L3/L4/L6, 括号匹配极易炸）。\n"
    "4. 【粗粒度逐项高亮 — 本场景核心动画规约】：\n"
    "   - 第1步：self.play(Write(formula), run_time>=0.8) 把整条公式整体写出, 然后 self.wait（按讲解词字数 \u201c每6个中文字>=1秒\u201d, 不少于 2 秒）。\n"
    "   - 第2步：**按 highlights 的顺序**逐条讲解, 第 i 条要点：\n"
    "       a) 在公式下方依次 FadeIn 一行中文注解 Text（font_size=18~20）, 多条注解**累加显示、不清屏**（遵守通用铁律的累加显示原则）, 用 VGroup.arrange(DOWN, buff=0.3) 或逐行 next_to 往下排, 整体不超出 y=-3.0。\n"
    "       b) 同时对整条公式做一次 self.play(Indicate(formula)) 作为视觉提示（指向当前正在讲的公式整体, 不要去 indicate 公式的某个子串）。\n"
    "       c) 每条要点之间 self.wait（按该条注解中文字数估算时长, 不少于 1.5 秒）, 给解说留出时间。\n"
    "   - 第3步：所有要点讲完后, self.play(FadeOut(...)) 统一清屏。\n"
    "5. 【禁止拆式】不要把公式拆成分项做 TransformMatchingTex, 不要 set_color_by_tex 给子项上色。逐项高亮一律通过\u201c公式下方逐条累加中文注解 + 对整条公式 Indicate\u201d实现, 以规避括号/子串匹配炸裂的风险。\n"
    "6. 注解中文文字不要指定 font 参数（用系统默认字体）。\n"
    + _MANIM_COMMON_RULES + _MANIM_LATEX_RULES +
    "仅输出完整的 Python 代码（一个 ```python``` 代码块或 Write 到 <scene_name>.py），不要额外解释文字。\n"
)

prompts_dict["manim_generate_architecture"] = (
    "【代码生成铁律 — 必须严格遵守】:\n- 这是一个独立的代码生成任务。不要 read / cat / inspect 工作目录中任何已存在的 .py 文件（它们是历史产物）。当 prompt 提供 \"论文原文路径\" 或 \"图像分析路径\" 时, 请使用 Read 工具读取该 .txt / .json 文件作为参考依据, 但禁止读取任何 .py 历史产物。\n- 推荐使用 Write 工具把最终代码写入当前工作目录下的 \\texttt{<scene_name>.py} (TitleScene.py / IntroScene.py / MethodScene.py / ResultsScene.py); 可用 Bash 运行 manim render -ql <scene_name>.py <scene_name> 自测语法与渲染。\n- 工作区严格限定: Write 与 Bash 只能在当前 cwd (已隔离到 temp_dir) 内操作; 禁止读写 cwd 之外的任何路径 (除 prompt 提供的 \"论文原文路径\" 或 \"图像分析路径\"); 不要 cd 到其他目录, 不要碰项目根的 .py 历史产物。\n- 输出方式两选一即可: 把代码 Write 到 \\texttt{<scene_name>.py} 文件 (推荐, 更稳定), 或在 stdout 输出单个 ```python ... ``` markdown 代码块。\n- 直接基于下面给定的论文内容与分析数据，从零开始写完整可运行的 Manim 代码。\n- 输出必须是唯一一个 ```python ... ``` markdown 代码块，包含完整可运行的 Manim Scene。\n- 若工作目录中已有同名场景文件（TitleScene.py / MethodScene.py / IntroScene.py / ResultsScene.py 等），请全部忽略，它们是无关历史产物。\n- 严禁输出 “已有/查看/已经满足需求/不需要修改” 这类描述语。\n\n"
    "你是 ManimCE (Manim Community Edition) 专家。请生成一个展示模型架构的 Manim Scene。\n\n"
    "代码要求：\n"
    "1. 使用 `from manim import *`\n"
    "2. 类名使用提供的 scene_name\n"
    "3. 架构图设计：\n"
    "   - 每个模块用 Rectangle(width=2.0, height=0.7) + Text(font_size=18)\n"
    "   - 最多 4 个模块，从上到下或从左到右排列\n"
    "   - 如果超过 4 个模块，分两页展示：先展示前半部分（FadeIn → Wait → FadeOut），再展示后半部分\n"
    "   - 用 Arrow(stroke_width=2, buff=0.15) 连接\n"
    "   - 不同模块用不同颜色（BLUE, GREEN, YELLOW, RED, PURPLE）\n"
    "4. 动画流程：\n"
    "   - 先显示标题，然后逐个 FadeIn 模块 + GrowArrow 连接\n"
    "   - 最后 Indicate 高亮核心模块\n"
    "   - 总共不超过 10 个 play() 调用\n"
    "5. 所有模块位置必须手动计算，确保不重叠、不超框\n"
    + _MANIM_COMMON_RULES + _MANIM_ARCHITECTURE_RULES +
    "仅输出完整的 Python 代码，不要 markdown 代码块标记，不要解释文字。\n"
)

prompts_dict["manim_generate_flow"] = (
    "【代码生成铁律 — 必须严格遵守】:\n- 这是一个独立的代码生成任务。不要 read / cat / inspect 工作目录中任何已存在的 .py 文件（它们是历史产物）。当 prompt 提供 \"论文原文路径\" 或 \"图像分析路径\" 时, 请使用 Read 工具读取该 .txt / .json 文件作为参考依据, 但禁止读取任何 .py 历史产物。\n- 推荐使用 Write 工具把最终代码写入当前工作目录下的 \\texttt{<scene_name>.py} (TitleScene.py / IntroScene.py / MethodScene.py / ResultsScene.py); 可用 Bash 运行 manim render -ql <scene_name>.py <scene_name> 自测语法与渲染。\n- 工作区严格限定: Write 与 Bash 只能在当前 cwd (已隔离到 temp_dir) 内操作; 禁止读写 cwd 之外的任何路径 (除 prompt 提供的 \"论文原文路径\" 或 \"图像分析路径\"); 不要 cd 到其他目录, 不要碰项目根的 .py 历史产物。\n- 输出方式两选一即可: 把代码 Write 到 \\texttt{<scene_name>.py} 文件 (推荐, 更稳定), 或在 stdout 输出单个 ```python ... ``` markdown 代码块。\n- 直接基于下面给定的论文内容与分析数据，从零开始写完整可运行的 Manim 代码。\n- 输出必须是唯一一个 ```python ... ``` markdown 代码块，包含完整可运行的 Manim Scene。\n- 若工作目录中已有同名场景文件（TitleScene.py / MethodScene.py / IntroScene.py / ResultsScene.py 等），请全部忽略，它们是无关历史产物。\n- 严禁输出 “已有/查看/已经满足需求/不需要修改” 这类描述语。\n\n"
    "你是 ManimCE (Manim Community Edition) 专家。请生成一个展示算法流程的 Manim Scene。\n\n"
    "代码要求：\n"
    "1. 使用 `from manim import *`\n"
    "2. 类名使用提供的 scene_name\n"
    "3. 流程图设计：\n"
    "   - 最多 4 个步骤节点，用 RoundedRectangle(width=2.0, height=0.6, corner_radius=0.15) + Text(font_size=16)\n"
    "   - 如果内容多于 4 个节点，分两页展示：先展示前 2 个 FadeOut，再展示后 2 个\n"
    "   - 从左到右排列，或分两行排列（上行3个，下行2个）\n"
    "   - 用 Arrow(stroke_width=2, buff=0.15) 连接\n"
    "4. 动画流程：\n"
    "   - 显示标题，然后逐步 Create 节点 + GrowArrow\n"
    "   - 可选：用 Dot 沿路径移动表示数据流\n"
    "   - 总共不超过 10 个 play() 调用\n"
    "5. 整体布局用 VGroup 管理，用 .arrange() 或手动定位，确保不超框\n"
    + _MANIM_COMMON_RULES + _MANIM_ARCHITECTURE_RULES +
    "仅输出完整的 Python 代码，不要 markdown 代码块标记，不要解释文字。\n"
)

prompts_dict["manim_generate_title"] = (
    "【代码生成铁律 — 必须严格遵守】:\n- 这是一个独立的代码生成任务。不要 read / cat / inspect 工作目录中任何已存在的 .py 文件（它们是历史产物）。当 prompt 提供 \"论文原文路径\" 或 \"图像分析路径\" 时, 请使用 Read 工具读取该 .txt / .json 文件作为参考依据, 但禁止读取任何 .py 历史产物。\n- 推荐使用 Write 工具把最终代码写入当前工作目录下的 \\texttt{<scene_name>.py} (TitleScene.py / IntroScene.py / MethodScene.py / ResultsScene.py); 可用 Bash 运行 manim render -ql <scene_name>.py <scene_name> 自测语法与渲染。\n- 工作区严格限定: Write 与 Bash 只能在当前 cwd (已隔离到 temp_dir) 内操作; 禁止读写 cwd 之外的任何路径 (除 prompt 提供的 \"论文原文路径\" 或 \"图像分析路径\"); 不要 cd 到其他目录, 不要碰项目根的 .py 历史产物。\n- 输出方式两选一即可: 把代码 Write 到 \\texttt{<scene_name>.py} 文件 (推荐, 更稳定), 或在 stdout 输出单个 ```python ... ``` markdown 代码块。\n- 直接基于下面给定的论文内容与分析数据，从零开始写完整可运行的 Manim 代码。\n- 输出必须是唯一一个 ```python ... ``` markdown 代码块，包含完整可运行的 Manim Scene。\n- 若工作目录中已有同名场景文件（TitleScene.py / MethodScene.py / IntroScene.py / ResultsScene.py 等），请全部忽略，它们是无关历史产物。\n- 严禁输出 “已有/查看/已经满足需求/不需要修改” 这类描述语。\n\n"
    "你是 ManimCE (Manim Community Edition) 专家。请生成一个展示论文标题和核心贡献的 Manim Scene。\n\n"
    "代码要求：\n"
    "1. 使用 `from manim import *`\n"
    "2. 类名使用提供的 scene_name\n"
    "3. 展示内容：\n"
    "   - 论文英文原标题（Text, font_size=32, color=BLUE），居中显示\n"
    "   - 1-3 个核心贡献点，必须使用中文（Text, font_size=20），逐条出现在标题下方\n"
    "   - 每条贡献点不超过 20 个字！超过的截断或分两行。每条之间 buff=0.3\n"
    "   - 如果标题过长（超过 40 字符），用 font_size=26 或换行\n"
    "4. 动画流程（必须严格按下列顺序，不得擅自插入 FadeOut）：\n"
    "   - Step 1: Write(标题) → self.wait(1)\n"
    "   - Step 2: 逐条 FadeIn 贡献点。每条 FadeIn 后 self.wait(2) 然后**直接进入下一条 FadeIn**。所有贡献点 FadeIn 完成后**必须同时保留在屏幕上**，禁止单独对任何一条贡献点调用 FadeOut。\n"
    "   - Step 3: 全部贡献点 FadeIn 完成后再 self.wait(2)\n"
    "   - Step 4: 最后一次性 self.play(FadeOut(标题, *全部贡献点)) 清屏\n"
    "   - 推荐写法示例：\n"
    "     ```\n"
    "     self.play(Write(title)); self.wait(1)\n"
    "     self.play(FadeIn(b1)); self.wait(2)\n"
    "     self.play(FadeIn(b2)); self.wait(2)\n"
    "     self.play(FadeIn(b3)); self.wait(2)  # 此时屏幕同时有 title + b1 + b2 + b3\n"
    "     self.play(FadeOut(title, b1, b2, b3))\n"
    "     ```\n"
    "   - 禁止写法（单独消失再出下一条）：\n"
    "     ```\n"
    "     self.play(FadeIn(b1)); self.wait(2); self.play(FadeOut(b1))  # ❌ 禁止\n"
    "     self.play(FadeIn(b2)); self.wait(2); self.play(FadeOut(b2))  # ❌ 禁止\n"
    "     ```\n"
    "   - 总共不超过 10 个 play() 调用\n"
    "5. 所有文字居中排列，用 VGroup + arrange(DOWN, buff=0.5)\n"
    "6. 【语言要求】论文标题保留英文原文，其余所有文字（贡献点、注释等）必须使用中文。\n"
    + _MANIM_COMMON_RULES +
    "仅输出完整的 Python 代码，不要 markdown 代码块标记，不要解释文字。\n"
)

prompts_dict["manim_generate_results"] = (
    "【代码生成铁律 — 必须严格遵守】:\n- 这是一个独立的代码生成任务。不要 read / cat / inspect 工作目录中任何已存在的 .py 文件（它们是历史产物）。当 prompt 提供 \"论文原文路径\" 或 \"图像分析路径\" 时, 请使用 Read 工具读取该 .txt / .json 文件作为参考依据, 但禁止读取任何 .py 历史产物。\n- 推荐使用 Write 工具把最终代码写入当前工作目录下的 \\texttt{<scene_name>.py} (TitleScene.py / IntroScene.py / MethodScene.py / ResultsScene.py); 可用 Bash 运行 manim render -ql <scene_name>.py <scene_name> 自测语法与渲染。\n- 工作区严格限定: Write 与 Bash 只能在当前 cwd (已隔离到 temp_dir) 内操作; 禁止读写 cwd 之外的任何路径 (除 prompt 提供的 \"论文原文路径\" 或 \"图像分析路径\"); 不要 cd 到其他目录, 不要碰项目根的 .py 历史产物。\n- 输出方式两选一即可: 把代码 Write 到 \\texttt{<scene_name>.py} 文件 (推荐, 更稳定), 或在 stdout 输出单个 ```python ... ``` markdown 代码块。\n- 直接基于下面给定的论文内容与分析数据，从零开始写完整可运行的 Manim 代码。\n- 输出必须是唯一一个 ```python ... ``` markdown 代码块，包含完整可运行的 Manim Scene。\n- 若工作目录中已有同名场景文件（TitleScene.py / MethodScene.py / IntroScene.py / ResultsScene.py 等），请全部忽略，它们是无关历史产物。\n- 严禁输出 “已有/查看/已经满足需求/不需要修改” 这类描述语。\n\n"
    "你是 ManimCE (Manim Community Edition) 专家。请生成一个展示论文实验结果的 Manim Scene。\n\n"
    "代码要求：\n"
    "1. 使用 `from manim import *`\n"
    "2. 类名使用提供的 scene_name\n"
    "3. 展示方式（用 Text 列表，禁止用 Rectangle 柱状图）：\n"
    "   - 标题 Text(font_size=22, color=YELLOW) 居中置顶\n"
    "   - 每条结果用 Text(font_size=16)，格式：任务名 ... 数值 (提升)\n"
    "   - 数值用 GREEN 高亮，提升百分比用 YELLOW\n"
    "   - 最后一行用 font_size=18 + BOLD 显示平均值/总结\n"
    "   - 最多展示 4 条数据，超过的合并为平均值\n"
    "   - 如果有超过 4 条，分两页展示：前 2 条 FadeIn → Wait → FadeOut，后 2 条 FadeIn\n"
    "4. 动画：标题 Write → 逐条 FadeIn 数据 → 高亮平均值\n"
    "5. 最后保持内容在屏幕上，不要 FadeOut\n"
    "6. 数据必须从论文原文中提取真实数字，禁止编造\n"
    "7. 所有元素必须在 X[-7,7] Y[-4,4] 范围内，禁止使用 scale_to_fit_width。用合理的 font_size 和布局控制大小。\n"
    + _MANIM_COMMON_RULES +
    "仅输出完整的 Python 代码，不要 markdown 代码块标记，不要解释文字。\n"
)

# ---- 图像分析增强 Prompts ----

prompts_dict["manim_fix_code"] = (
    "【代码生成铁律 — 必须严格遵守】:\n- 这是一个独立的代码生成任务。不要 read / cat / inspect 工作目录中任何已存在的 .py 文件（它们是历史产物）。当 prompt 提供 \"论文原文路径\" 或 \"图像分析路径\" 时, 请使用 Read 工具读取该 .txt / .json 文件作为参考依据, 但禁止读取任何 .py 历史产物。\n- 推荐使用 Write 工具把最终代码写入当前工作目录下的 \\texttt{<scene_name>.py} (TitleScene.py / IntroScene.py / MethodScene.py / ResultsScene.py); 可用 Bash 运行 manim render -ql <scene_name>.py <scene_name> 自测语法与渲染。\n- 工作区严格限定: Write 与 Bash 只能在当前 cwd (已隔离到 temp_dir) 内操作; 禁止读写 cwd 之外的任何路径 (除 prompt 提供的 \"论文原文路径\" 或 \"图像分析路径\"); 不要 cd 到其他目录, 不要碰项目根的 .py 历史产物。\n- 输出方式两选一即可: 把代码 Write 到 \\texttt{<scene_name>.py} 文件 (推荐, 更稳定), 或在 stdout 输出单个 ```python ... ``` markdown 代码块。\n- 直接基于下面给定的论文内容与分析数据，从零开始写完整可运行的 Manim 代码。\n- 输出必须是唯一一个 ```python ... ``` markdown 代码块，包含完整可运行的 Manim Scene。\n- 若工作目录中已有同名场景文件（TitleScene.py / MethodScene.py / IntroScene.py / ResultsScene.py 等），请全部忽略，它们是无关历史产物。\n- 严禁输出 “已有/查看/已经满足需求/不需要修改” 这类描述语。\n\n"
    "你是 ManimCE 调试专家。给定一段有错误的 Manim 代码和错误信息，请修复代码并返回完整的修复后代码。\n\n"
    "修复要求：\n"
    "1. 仔细分析错误信息，找到根本原因\n"
    "2. 修复时保持原有动画逻辑不变\n"
    "3. 常见问题：\n"
    "   - LaTeX 语法错误 -> 检查括号匹配、反斜杠转义\n"
    "   - AttributeError -> 检查 ManimCE API 版本\n"
    "   - 元素超出画框 -> 调整位置或缩放\n"
    "   - AnimationGroup 空动画 -> 添加条件检查\n"
    + _MANIM_COMMON_RULES + _MANIM_LATEX_RULES +
    "仅输出完整的修复后 Python 代码，不要解释。\n"
)

prompts_dict["manim_generate_architecture_from_figure"] = (
    "【代码生成铁律 — 必须严格遵守】:\n- 这是一个独立的代码生成任务。不要 read / cat / inspect 工作目录中任何已存在的 .py 文件（它们是历史产物）。当 prompt 提供 \"论文原文路径\" 或 \"图像分析路径\" 时, 请使用 Read 工具读取该 .txt / .json 文件作为参考依据, 但禁止读取任何 .py 历史产物。\n- 推荐使用 Write 工具把最终代码写入当前工作目录下的 \\texttt{<scene_name>.py} (TitleScene.py / IntroScene.py / MethodScene.py / ResultsScene.py); 可用 Bash 运行 manim render -ql <scene_name>.py <scene_name> 自测语法与渲染。\n- 工作区严格限定: Write 与 Bash 只能在当前 cwd (已隔离到 temp_dir) 内操作; 禁止读写 cwd 之外的任何路径 (除 prompt 提供的 \"论文原文路径\" 或 \"图像分析路径\"); 不要 cd 到其他目录, 不要碰项目根的 .py 历史产物。\n- 输出方式两选一即可: 把代码 Write 到 \\texttt{<scene_name>.py} 文件 (推荐, 更稳定), 或在 stdout 输出单个 ```python ... ``` markdown 代码块。\n- 直接基于下面给定的论文内容与分析数据，从零开始写完整可运行的 Manim 代码。\n- 输出必须是唯一一个 ```python ... ``` markdown 代码块，包含完整可运行的 Manim Scene。\n- 若工作目录中已有同名场景文件（TitleScene.py / MethodScene.py / IntroScene.py / ResultsScene.py 等），请全部忽略，它们是无关历史产物。\n- 严禁输出 “已有/查看/已经满足需求/不需要修改” 这类描述语。\n\n"
    "你是 ManimCE (Manim Community Edition) 专家。请根据以下论文方法图的精确元素数据，"
    "生成一个忠实还原该架构图的 Manim Scene 动画。\n\n"
    "【核心原则】：你收到的元素数据包含精确的 Manim 坐标 (move_to 值)、尺寸和颜色。"
    "请直接使用这些坐标，不要自己猜测位置！\n\n"
    "代码要求：\n"
    "1. 使用 `from manim import *`\n"
    "2. 类名使用提供的 scene_name\n"
    "3. 对于「模块组」中的每个元素：\n"
    "   - 堆叠模块（多层）→ 用一个大 Rectangle 表示，标注层数\n"
    "   - 单个模块 → 用对应 shape + 颜色创建\n"
    "   - 直接使用给定的 move_to 坐标和 width/height\n"
    "4. 对于「箭头」：直接用 Arrow(start, end) 创建\n"
    "5. 用 Qwen-VL 分析的语义名称给模块标注 Text\n"
    "6. 动画：按数据流方向逐组 FadeIn 模块 + GrowArrow 连接\n"
    "7. 核心创新模块用 SurroundingRectangle 高亮\n"
    + _MANIM_COMMON_RULES + _MANIM_ARCHITECTURE_RULES +
    "仅输出完整的 Python 代码，不要 markdown 代码块标记，不要解释文字。\n"
)




prompts_dict["js_anim_generate"] = (
    "【代码生成铁律 — 必须严格遵守】:\n"
    "- 这是一个独立的代码生成任务。不要 read / cat / inspect 工作目录中任何已存在的文件（它们是历史产物）。从零开始写。\n"
    "- 仅输出唯一一个 ```html ... ``` markdown 代码块, 不要任何额外解释文字, 不要第二个代码块。\n"
    "- 必须完全自包含: 内联 JS + 内联 CSS, 禁止任何外部资源（禁止 CDN、禁止外链脚本/样式、禁止外部图片、禁止网络字体）。整页只用浏览器原生 API。\n"
    "- 严禁输出 “已有/查看/已经满足需求/不需要修改” 这类描述语。\n\n"
    "你是 Web 动画讲解专家。本任务的唯一目标是产出**一个自包含 HTML 文件**, 用逐帧确定性渲染的方式做一段知识讲解动画, 供录屏管线逐帧截图合成视频。\n\n"
    "【硬性技术契约 — 录屏管线强依赖, 必须严格逐条遵守】:\n"
    "1. 画布固定 1280×720: 用一个 <canvas width=\"1280\" height=\"720\"> (或等大的 <svg width=\"1280\" height=\"720\">); 白色背景; <body> 的 margin 和 padding 必须为 0, 不要让画布之外出现任何留白或滚动条。\n"
    "2. 必须在全局 (window 上) 定义三个成员, 录屏脚本会直接读取与调用:\n"
    "   - window.FPS: 帧率, 建议设为 24。\n"
    "   - window.TOTAL_FRAMES: 整数, 等于 目标秒数 × FPS (见下方目标时长说明)。\n"
    "   - window.renderFrame(frameIndex): 渲染函数, 入参为帧序号。\n"
    "3. window.renderFrame(n) 必须是**纯函数式确定渲染**: 对同一个 n, 任意时刻调用都渲染出完全相同的一帧; 函数内部先清空画布再完整重绘该帧, 不得依赖上一次调用留下的状态。\n"
    "4. 【严禁基于真实时间驱动动画】: 禁止用 setTimeout / setInterval / requestAnimationFrame / Date.now / performance.now 推进动画。录屏是逐帧调用 renderFrame(0), renderFrame(1), ... renderFrame(TOTAL_FRAMES-1) 后分别截图, 任何依赖真实流逝时间的动画都会全部失效。动画进度必须完全由 frameIndex 决定, 例如 `const t = n / window.TOTAL_FRAMES;` 得到 0→1 的归一化进度, 再据 t 插值出该帧所有元素的位置/透明度/形变。\n"
    "5. 页面加载完成后立即调用一次 window.renderFrame(0), 保证首帧可见。\n\n"
    "【目标时长】: 你会在下文收到 target_seconds (目标秒数)。据此设 `window.TOTAL_FRAMES = Math.round(target_seconds * window.FPS);`, 并把整段动画的节奏铺满这个时长。\n\n"
    "【两类示意的画法指导】: 你会在下文收到 kind, 取值为 concrete 或 abstract, 据此选择画法:\n"
    "- concrete (具象卡通示意, 如机械臂 / 夹爪 / 物体 / 叠衣服等物理场景): 用简洁色块、圆角矩形、路径表示物体, 通过关键姿态之间的插值做运动。例如: 夹爪开合 = 两个矩形的间距随 t 变化; 物体位移 = 坐标随 t 线性插值; 叠衣服 = 在几个关键帧姿态(摊开→对折→再折)之间按 t 分段插值矩形的翻折。扁平干净风格, 不追求拟真。\n"
    "- abstract (抽象机制示意, 如数据流 / 模块交互 / 注意力机制): 用方框 + 箭头 + 流动高亮 + 渐变表达; 元素随 t 依次出现、连线、再让高亮沿连线流动。\n"
    "- 通用风格: 扁平设计; 配色克制专业, 全程只用 2-3 种主色; 中文文字标注用 sans-serif 字体、居中、清晰可读; 适合知识讲解; 元素出现与运动带缓动(ease, 例如对 t 做 smoothstep 或三次缓动), 不要生硬线性。\n\n"
    "【下文输入说明】(以下字段会以自然语言形式出现在 user_content 中, 不是模板占位符):\n"
    "- scene_name: 产物文件名与主类/标题用名, 命名随意但需对应该场景。\n"
    "- 场景描述: 需要被可视化讲解的具体内容, 动画必须忠实于它, 不要画无关的通用示例。\n"
    "- target_seconds: 目标秒数, 用于计算 TOTAL_FRAMES。\n"
    "- kind: concrete 或 abstract, 决定上面的画法。\n\n"
    "仅输出唯一一个 ```html ... ``` 代码块, 包含完整可直接用浏览器打开的自包含页面。\n"
)
