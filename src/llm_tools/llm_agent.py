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
    # if os.path.exists("./cache"):
    #     shutil.rmtree("./cache")
    os.makedirs("./cache", exist_ok=True)
    return MANUALLY_EXTRACT_IMAGES, model, client

MANUALLY_EXTRACT_IMAGES, model, client = initialize_agent()


def _parse_json_response(raw: str):
    """尝试从 LLM 返回中解析 JSON 对象。"""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logging.warning("无法解析为 JSON: %s", raw[:2000])
    return {}

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


def generate_summary(text, word_budget: int = 1000):
    prompt_template = prompts_dict.get(inspect.currentframe().f_code.co_name, "")
    prompt = prompt_template.format(word_budget=word_budget) + text
    return create_chat_completion(prompt)

def generate_short_summary(text, word_budget: int = 120):
    prompt_template = prompts_dict.get(inspect.currentframe().f_code.co_name, "")
    prompt = prompt_template.format(word_budget=word_budget) + text
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

def generate_structured_video_plan(text):
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    raw = create_chat_completion(prompt, text)
    return _parse_json_response(raw)

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

    # 清理LLM返回的内容，移除markdown代码块标记
    cleaned_response = response.strip()
    if cleaned_response.startswith("```json"):
        cleaned_response = cleaned_response[7:]
    if cleaned_response.endswith("```"):
        cleaned_response = cleaned_response[:-3]
    cleaned_response = cleaned_response.strip()

    response2list = json.loads(cleaned_response)
    return response2list

def extract_captions_to_dict(text: str = ''):
    """
    从文本中提取图片和表格标题，返回字典格式
    
    参数:
    - text: 包含图片和表格标题的文本
    
    返回:
    - dict: {"fig_1": "图片标题1", "tab_1": "表格标题1", ...}
    """
    prompt = get_prompt(inspect.currentframe().f_code.co_name, text)
    response = create_chat_completion(prompt, text)
    
    # 清理LLM返回的内容，移除markdown代码块标记
    cleaned_response = response.strip()
    if cleaned_response.startswith("```json"):
        cleaned_response = cleaned_response[7:]
    if cleaned_response.endswith("```"):
        cleaned_response = cleaned_response[:-3]
    cleaned_response = cleaned_response.strip()

    try:
        # 尝试直接解析为字典
        result_dict = json.loads(cleaned_response)
        if isinstance(result_dict, dict):
            return result_dict
    except json.JSONDecodeError:
        logging.warning("LLM返回的不是有效JSON，尝试解析为列表格式")
    
    try:
        # 尝试解析为原有的列表格式 [[图片标题...], [表格标题...]]
        response_list = json.loads(cleaned_response)
        if isinstance(response_list, list) and len(response_list) == 2:
            fig_captions, tab_captions = response_list
            result_dict = {}
            
            # 处理图片标题
            for i, caption in enumerate(fig_captions, 1):
                if caption.strip():
                    result_dict[f"fig_{i}"] = caption.strip()
            
            # 处理表格标题
            for i, caption in enumerate(tab_captions, 1):
                if caption.strip():
                    result_dict[f"tab_{i}"] = caption.strip()
            
            return result_dict
    except (json.JSONDecodeError, ValueError, IndexError) as e:
        logging.error(f"解析标题失败: {e}")
        logging.error(f"LLM返回内容: {response}")
        return {}


def add_context_to_image_explanations(image_explanations):
    """为图像解释添加上下文和过渡语句

    Args:
        image_explanations: 图像解释列表，每个元素包含detailed_explanation等字段

    Returns:
        list: 添加了context和transition的图像解释列表
    """
    import json

    if not image_explanations or len(image_explanations) == 0:
        return image_explanations

    # 将图像解释转换为文本格式供LLM处理
    explanations_text = json.dumps(image_explanations, ensure_ascii=False, indent=2)

    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    response = create_chat_completion(prompt, explanations_text)

    # 清理LLM返回的内容，移除markdown代码块标记
    cleaned_response = response.strip()
    if cleaned_response.startswith("```json"):
        cleaned_response = cleaned_response[7:]
    if cleaned_response.endswith("```"):
        cleaned_response = cleaned_response[:-3]
    cleaned_response = cleaned_response.strip()

    try:
        # 解析LLM返回的结果
        updated_explanations = json.loads(cleaned_response)
        if isinstance(updated_explanations, list) and len(updated_explanations) == len(image_explanations):
            logging.info("成功为图像解释添加上下文和过渡语句")
            return updated_explanations
        else:
            logging.warning("LLM返回结果格式不正确，保持原始解释")
            return image_explanations
    except json.JSONDecodeError as e:
        logging.error(f"解析LLM返回的JSON失败: {e}")
        logging.error(f"LLM返回内容: {response}")
        return image_explanations


def rate_image_importance(captions: list) -> list:
    """对一组图片的题注/描述进行重要性打分。

    Args:
        captions: 图片描述列表

    Returns:
        list[int]: 每张图片的重要性分数（1-10）
    """
    if not captions:
        return []

    captions_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(captions))
    prompt = get_prompt(inspect.currentframe().f_code.co_name)
    response = create_chat_completion(prompt, captions_text)

    parsed = _parse_json_response(response)
    scores = parsed.get("scores", [])

    if len(scores) != len(captions):
        logging.warning(f"图片打分结果长度不匹配: 期望 {len(captions)}, 实际 {len(scores)}")
        return [5] * len(captions)

    return [int(s) if isinstance(s, (int, float)) else 5 for s in scores]


def select_top_images(items: list, scores: list, top_n: int = 5) -> list:
    """根据分数选出 top-N 项，保持原始顺序。

    Args:
        items: 待筛选列表
        scores: 对应分数列表
        top_n: 选取数量

    Returns:
        list: 按原始顺序排列的 top-N 项
    """
    if len(items) <= top_n:
        return items[:]

    indexed = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)
    top_indices = sorted([idx for idx, _ in indexed[:top_n]])
    return [items[i] for i in top_indices]

