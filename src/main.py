import sys
import datetime
import logging
import argparse

from paperagent_workflow import generate_daily_arxiv_summary

logging.basicConfig(
    level=logging.DEBUG,  # 修改为 DEBUG 级别
    format='%(asctime)s - %(levelname)s - %(message)s'
)
file_handler = logging.FileHandler('app.log', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(file_handler)

def parse_args():
    parser = argparse.ArgumentParser(description="Arxiv Paper Processing Script")
    #papername
    parser.add_argument(
        "--filename",
        type=str,
        help="The filename to process, e.g., 'cs.RO' for robotics papers. or a paper tile"
    )
    #output length
    parser.add_argument(
        "--video_length",
        type=str,
        default="long",
        choices=["long", "short"],
        help="Output format: 'long' for detailed summaries, 'short' for brief summaries"
    )
    #output language default is Chinese
    parser.add_argument(
        "--output_language",
        type=str,
        default="zh",
        choices=["zh", "en"],
        help="Output language: 'zh' for Chinese, 'en' for English"
    )
    
    return parser.parse_args()


if __name__ == "__main__":

    args= parse_args()
    filename = args.filename
    language = args.output_language
    
    # 动态更新语言配置
    if language:
        import src.config as config
        config.OUTPUT_LANGUAGE = language
        # 重新初始化提示词
        from src.llm_tools.prompts import BASE_PROMPTS, get_language_suffix
        from src.llm_tools import prompts
        # 重新生成提示词字典
        language_suffix = get_language_suffix()
        for key, prompt_dict in BASE_PROMPTS.items():
            if isinstance(prompt_dict, dict):
                prompt = prompt_dict.get(language, prompt_dict.get("zh", ""))
            else:
                prompt = prompt_dict
            prompts.prompts_dict[key] = prompt + language_suffix
    
    try:
        today=datetime.datetime.now()
        yesterday=today-datetime.timedelta(days=400)
        yesterday=yesterday.strftime(r"%Y-%m-%d")
        today=today.strftime(r"%Y-%m-%d")
        logging.info("今天是%s,昨天是%s", today, yesterday)
        # path,titles=generate_daily_arxiv_summary(query='cs.RO',max_papers=100,date=str(yesterday))
        path,titles,cn_titles=generate_daily_arxiv_summary(query=filename,max_papers=1,date=str(yesterday),long_or_short="long")
        from auto_upload_bilibili import upload_video_to_bilibili
        if len(titles)==1:
            upload_video_to_bilibili(path,cn_titles[0],"人工智能,具身智能,机器人,模仿学习,强化学习,自动驾驶,具身人机", titles)
        else:
            upload_video_to_bilibili(path, "Arxiv具身日报"+str(today), "人工智能,具身智能,机器人,模仿学习,强化学习,自动驾驶,具身人机", titles)
    except Exception as e:
        logging.error("程序运行时发生异常: %s", e)
        raise e
    finally:
        logging.info("程序结束")
        logging.shutdown()
