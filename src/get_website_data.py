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


def download_videos_files(url, download_folder='./pic'):
    if not url:
        logging.warning("未提供视频网址，跳过下载")
        return False

    os.makedirs(download_folder, exist_ok=True)

    session = requests.Session()
    try:
        response = session.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.error("获取网页失败 %s: %s", url, exc)
        return False

    soup = BeautifulSoup(response.text, 'html.parser')
    video_tags = soup.find_all('video')
    logging.info("在页面 %s 上找到 %d 个 video 标签", url, len(video_tags))

    downloaded = 0
    for idx, video_tag in enumerate(video_tags):
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
            video_response = session.get(video_url, stream=True, headers=HEADERS, timeout=30)
            video_response.raise_for_status()
            with open(video_path, 'wb') as f:
                for chunk in video_response.iter_content(chunk_size=1024 * 512):
                    if not chunk:
                        continue
                    f.write(chunk)
            downloaded += 1
        except requests.RequestException as exc:
            logging.warning("下载视频 %d 失败(%s): %s", idx, video_url, exc)
        except Exception as exc:  # pragma: no cover
            logging.error("保存视频 %d 时发生未知错误: %s", idx, exc)

    if downloaded == 0:
        logging.info("页面 %s 未获取到任何可下载视频", url)
    return downloaded > 0

if __name__ == "__main__":
    # 示例 URL
    website_url = "https://superrobobrain.github.io/"
    download_videos_files(website_url)