import os
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# 配置日志记录
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0 Safari/537.36"
}


def download_videos_files(url, download_folder='./pic', page_timeout=30,
                          video_timeout=120, max_videos=10):
    """从指定网页下载视频文件。

    Args:
        url: 目标网页地址
        download_folder: 视频保存目录
        page_timeout: 页面请求超时秒数
        video_timeout: 单个视频下载超时秒数
        max_videos: 最大下载视频数量，防止意外下载过多

    Returns:
        bool: 是否成功下载了至少一个视频
    """
    if not url or not isinstance(url, str):
        logging.warning("未提供有效的视频网址，跳过下载")
        return False

    # 基本 URL 格式校验
    if not url.startswith(('http://', 'https://')):
        logging.warning("视频网址格式无效（需以 http/https 开头）: %s", url)
        return False

    os.makedirs(download_folder, exist_ok=True)

    session = requests.Session()
    try:
        response = session.get(url, headers=HEADERS, timeout=page_timeout)
        response.raise_for_status()
    except requests.ConnectionError as exc:
        logging.error("网络连接失败 %s: %s", url, exc)
        return False
    except requests.Timeout as exc:
        logging.error("请求超时 %s: %s", url, exc)
        return False
    except requests.RequestException as exc:
        logging.error("获取网页失败 %s: %s", url, exc)
        return False

    try:
        soup = BeautifulSoup(response.text, 'html.parser')
    except Exception as exc:
        logging.error("解析网页 HTML 失败 %s: %s", url, exc)
        return False

    video_tags = soup.find_all('video')
    logging.info("在页面 %s 上找到 %d 个 video 标签", url, len(video_tags))

    downloaded = 0
    for idx, video_tag in enumerate(video_tags):
        if idx >= max_videos:
            logging.info("已达到最大下载数量 %d，停止下载", max_videos)
            break

        video_url = video_tag.get('src')
        if not video_url:
            source_tag = video_tag.find('source')
            if source_tag:
                video_url = source_tag.get('src')

        if not video_url:
            logging.debug("视频 %d 没有可用的 src，跳过", idx)
            continue

        video_url = urljoin(url, video_url)
        video_path = os.path.join(download_folder, f"{idx}.mp4")

        try:
            logging.info("正在从 %s 下载视频 %d", video_url, idx)
            video_response = session.get(
                video_url, stream=True, headers=HEADERS, timeout=video_timeout
            )
            video_response.raise_for_status()
            with open(video_path, 'wb') as f:
                for chunk in video_response.iter_content(chunk_size=1024 * 512):
                    if not chunk:
                        continue
                    f.write(chunk)
            # 验证文件非空
            if os.path.getsize(video_path) == 0:
                logging.warning("下载的视频 %d 文件为空，删除", idx)
                os.remove(video_path)
                continue
            downloaded += 1
        except requests.ConnectionError as exc:
            logging.warning("下载视频 %d 连接失败(%s): %s", idx, video_url, exc)
        except requests.Timeout as exc:
            logging.warning("下载视频 %d 超时(%s): %s", idx, video_url, exc)
        except requests.RequestException as exc:
            logging.warning("下载视频 %d 失败(%s): %s", idx, video_url, exc)
        except OSError as exc:
            logging.error("保存视频 %d 磁盘写入失败: %s", idx, exc)
        except Exception as exc:
            logging.error("保存视频 %d 时发生未知错误: %s", idx, exc)

    if downloaded == 0:
        logging.info("页面 %s 未获取到任何可下载视频", url)
    return downloaded > 0

if __name__ == "__main__":
    # 示例 URL
    website_url = "https://superrobobrain.github.io/"
    download_videos_files(website_url)