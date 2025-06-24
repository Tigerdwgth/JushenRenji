import os
import re
import dashscope
import json
import sys
import shutil
from openai import OpenAI
import logging
import yaml
from config import *
# 配置日志记录
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,  # 修改为 DEBUG 级别
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def load_config():
    """
    从 config.yaml 文件中加载配置。
    return: dict，包含配置项。
    """
    config_path = "config.yaml"
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件 {config_path} 不存在，请创建该文件并添加所需配置。")
    
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return config


def initialize_agent():
    """
    初始化代理程序。

    功能：
    - 设置全局变量 `MANUALLY_EXTRACT_IMAGES`，用于控制是否手动提取 PDF 图片。
    - 设置模型名称，默认为 'deepseek'。

    注意：
    - 该函数目前仅初始化了一些变量，未包含实际的逻辑处理。
    """
    # 是否手动提取 PDF 图片
    MANUALLY_EXTRACT_IMAGES = False
    # 设置模型名称
    MODEL = 'qwen'
    MODEL = 'deepseek'
    config = load_config()
    # OPENAI_API_KEY"
    # "DASHSCOPE_API_KEY"
    # print(config)
    try:
        # 从配置文件或环境变量中获取 OpenAI API 密钥
        if API_KEYS.get('openai'):
            api_key = API_KEYS['openai']
        elif config.get("llm_api_key"):
            api_key = config["llm_api_key"]
        else:
            raise ValueError("请在 config.yaml 或环境变量中设置 OPENAI_API_KEY")

        # 从配置文件或环境变量中获取 DashScope API 密钥
        if API_KEYS.get('dashscope'):
            dashscope.api_key = API_KEYS['dashscope']
        elif config.get("dashscope_api_key"):
            dashscope.api_key = config["dashscope_api_key"]
        else:
            raise ValueError("请在 config.yaml 或环境变量中设置 DASHSCOPE_API_KEY")
    except KeyError as e:
            print(f"配置文件中缺少必要的键: {e}")
        

    if MODEL == 'qwen':
        model = 'qwen-max'
        url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    elif MODEL == 'deepseek':
        model = 'deepseek-chat'
        url = 'https://api.deepseek.com/v1'
# 初始化 OpenAI 客户端
# 验证当前使用的Python路径
    logging.info("当前Python解释器路径: %s", sys.executable)
    if MODEL == 'qwen':
        client = OpenAI(
        api_key=dashscope.api_key,
        base_url=url
    )
    elif MODEL == 'deepseek':
        client = OpenAI(
        api_key = api_key,
        base_url=url
    )
    # rm -rf ./cache on windows
    if os.path.exists("./cache"):
        shutil.rmtree("./cache")
    os.makedirs("./cache")
    return MANUALLY_EXTRACT_IMAGES, model, client

MANUALLY_EXTRACT_IMAGES, model,client= initialize_agent()

def generate_summary(text):
    prompt = (
        "请总结以下论文的核心内容,重点讲解方法，参考摘要，请使用简洁的表达，生成约1000字的总结。"
        "禁止输出markdown形式的文本，不要一条一条的列出，而是以长文的形式。"
        "你的目标是帮助用户快速理解论文核心内容，语言通俗易懂，适合制作论文讲解视频的文案。"
        "请以 “这篇文章...”作为开始，不要重复文章标题\n" + text
    )
    return create_chat_completion(prompt)
def generate_short_summary(text):
    prompt = ("""你现在是组会分享论文的研究生，请分享下面的文章，严格遵循以下要求。
              1.简单介绍一下文章工作单位（使用缩写），不用说明作者名字，
              2. 如果有提到是什么会议也请说明（仅使用缩写+年份形式）,没有提及的话，请直接忽略这个要求，不用说未提及，请勿编造任何信息。
              3. 用两句话简短介绍一下这篇文章的核心方法、模型结构和贡献，言简意赅。
              4. 禁止复读论文标题
              5. 禁止使用markdown形式的输出，请用完整的句子，而非列举点,使用中文"""+text)
    return create_chat_completion(prompt)
    

def generate_video_title(text):
    prompt = (
        "为讲解视频生成一个简介易懂明了吸引人的中文标题，仅输出标题不输出其他内容，"
        "禁止输出多余内容，与标点符号，不要标题加引号。"
    )
    ret_str=create_chat_completion(prompt, text)
    #使用正则表达式过滤掉不能出现在路径的字符
    ret_str = re.sub(r'[\\/:*?"<>|]', '', ret_str)
    return ret_str


def generate_origin_title(text):
    prompt = "论文的标题是什么？仅输出论文英文标题,不输出任何其他的文字"
    return create_chat_completion(prompt, text)
def generate_video_proceedings(text):
    prompt = "请问这篇论文是发表在哪个会议或期刊上的？仅输出会议或期刊名称如ICRA2025，CVPR2024，不输出其他多余文字,如果文字中没有提到请输出Arxiv2025"
    return create_chat_completion(prompt, text)

def get_paper_demo_website(text):
    prompt = """请问这篇论文的视频网址是什么？,请以json格式输出,需要可以被python解析,禁止输出其他多余文字，禁止输出markdown，仅输出最终json,格式：{"state":"0/1之间的一个代表失败或成功","url":"http://www.proj-demo.com"}
    """
    ret= create_chat_completion(prompt, text)
    
    logging.info(f"{ret}")
    # 使用正则表达式提取 JSON 部分
    json_re = re.compile(r"\{.*?\}", re.DOTALL)  # 非贪婪匹配，支持换行符
    match = json_re.search(ret)
    if match:
        json_str = match.group()  # 提取匹配到的 JSON 字符串
        try:
            # 尝试解析 JSON
            parsed_json = json.loads(json_str)
            logging.info("解析成功: %s", parsed_json)
        except json.JSONDecodeError as e:
            logging.error("JSON 解析失败: %s", e)
            return ''
    else:
        logging.warning("未找到 JSON 内容")
    if parsed_json['state'] not in ['0','1',0,1]:
        logging.warning("state值不在范围内")
        return ''
    if parsed_json['state']=='1'or parsed_json['state']==1:
        return parsed_json['url']
    else:
        logging.warning("未找到视频网址")
        return ''

def create_chat_completion(prompt, user_content=None):
    messages = [{"role": "system", "content": prompt}]
    if user_content:
        messages.append({"role": "user", "content": user_content})
    response = client.chat.completions.create(
        model=model,
        messages=messages
    )
    return response.choices[0].message.content

def get_captions_from_page(text:str=''):
    """
    从当前的页面中获取图片和表格对应的题注。
    要求获取图片和表格的题注，然后后按照[[图片题注1,图片题注2...],[表格题注1,表格题注2...]]的格式返回。
    如果没有题注，则返回空列表。
    :param text: 当前页面的文本内容，默认为空字符串。
    :return: 包含图片和表格题注的列表，如果没有题注，则返回空列表[[],[]]。

    """
    prompt = (
        "请从以下文本中提取图片和表格的题注,题注可能是英文或者还是中文的，比如fig，table等，"
        "要求提取图片题注和表格题注，分别放在两个列表中，"
        "返回格式为[[图片题注1,图片题注2...],[表格题注1,表格题注2...]]，"
        "如果没有图片或表格题注，则对应的列表为空。"
        "禁止输出markdown形式的文本，禁止输出多余内容，"
        "禁止输出其他格式的文本，禁止输出其他内容。"
        "请确保提取的题注是完整的句子，"
        "如果题注中包含图片或表格的编号，请保留编号。"
        "example: "
        "文本内容：图1：这是一个示例图片，表1：这是一个示例表格。\n"
        "返回格式：[['图1：这是一个示例图片'], ['表1：这是一个示例表格']]\n"
        "请从以下文本中提取图片和表格的题注：\n"    
    )
    response = create_chat_completion(prompt,text)
    # ['图1：这是一个示例图片', '表1：这是一个示例表格']
    # 解析这样一个字符串
    response2list= json.loads(response)
    # import pdb
    # pdb.set_trace()
    return response2list
    
