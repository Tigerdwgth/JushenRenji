import os
import re
import dashscope
import json
import sys
import shutil
from openai import OpenAI
import logging
import yaml
import inspect
from src.config import *
from src.llm_tools.prompts import prompts_dict
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

def get_prompt(func_name, text=None):
    """
    根据函数名称从 prompts_dict 中获取对应的 prompt。
    如果提供了 text，则将 text 附加到 prompt 后。
    """
    prompt = prompts_dict.get(func_name, "")
    if not prompt:
        logging.warning(f"未找到函数 {func_name} 对应的 prompt")
    if text:
        prompt += text
    return prompt


def generate_summary(text):
    prompt = get_prompt(inspect.currentframe().f_code.co_name, text)
    return create_chat_completion(prompt)

def generate_short_summary(text):
    prompt = get_prompt(inspect.currentframe().f_code.co_name, text)
    return create_chat_completion(prompt)

def generate_video_title(text):
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    ret_str = create_chat_completion(prompt, text)
    #使用正则表达式过滤掉不能出现在路径的字符
    ret_str = re.sub(r'[\\/:*?"<>|]', '', ret_str)
    return ret_str

def generate_origin_title(text):
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    return create_chat_completion(prompt, text)

def generate_video_proceedings(text):
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    return create_chat_completion(prompt, text)

def get_paper_demo_website(text):
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    ret = create_chat_completion(prompt, text)
    
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

def get_captions_from_page(text: str = ''):
    prompt = get_prompt(inspect.currentframe().f_code.co_name, text)
    response = create_chat_completion(prompt, text)
    response2list = json.loads(response)
    return response2list

