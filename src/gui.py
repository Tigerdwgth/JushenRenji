import gradio as gr
import datetime
import logging


def process_arxiv_summary(query, max_papers, long_or_short):
    try:
        today = datetime.datetime.now()
        yesterday = today - datetime.timedelta(days=1)
        yesterday = yesterday.strftime(r"%Y-%m-%d")
        today = today.strftime(r"%Y-%m-%d")
        
        logging.info("今天是%s,昨天是%s", today, yesterday)
        
        path, titles, cn_titles = generate_daily_arxiv_summary(
            query=query, max_papers=max_papers, date=str(yesterday), long_or_short=long_or_short
        )
        
        
        return f"视频上传成功！标题: {titles}"
    except Exception as e:
        logging.error("程序运行时发生异常: %s", e)
        return f"发生错误: {e}"
    finally:
        logging.info("程序结束")
        logging.shutdown()

# 创建 Gradio 界面
query_input = gr.Textbox(label="查询关键词", placeholder="请输入查询关键词，例如 'cs.RO'")
max_papers_input = gr.Number(label="最大论文数", value=1)
long_or_short_input = gr.Radio(
    ["long", "short"], label="摘要类型", value="long", interactive=True
)

interface = gr.Interface(
    fn=process_arxiv_summary,
    inputs=[query_input, max_papers_input, long_or_short_input],
    outputs="text",
    title="具身人机 Arxiv 视频生成器",
    description="输入查询关键词和参数，生成并上传具身智能相关的视频到 Bilibili。",
)

if __name__ == "__main__":
    interface.launch()