import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging

# 配置日志记录
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,  # 修改为 DEBUG 级别
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def download_videos_from_url(url, download_folder='./pic'):
    # 创建下载文件夹
    if not os.path.exists(download_folder):
        os.makedirs(download_folder)
        
    # 获取网页内容
    response = requests.get(url)
    if response.status_code != 200:
        print(f"获取网页失败: {url}")
        return
    else:
        print(f"成功获取网页内容: {url}")

    # 解析网页内容
    soup = BeautifulSoup(response.text, 'html.parser')
    video_tags = soup.find_all('video')
    print(f"在页面上找到 {len(video_tags)} 个视频标签。")

    # 下载视频
    for idx, video_tag in enumerate(video_tags):
        # 尝试从 <video> 的 src 属性获取 URL
        video_url = video_tag.get('src')

        # 如果 <video> 没有 src 属性，尝试从 <source> 标签获取
        if not video_url:
            source_tag = video_tag.find('source')
            if source_tag:
                video_url = source_tag.get('src')

        if not video_url:
            print(f"视频 {idx} 没有 URL，跳过。")
            continue

        # 处理相对路径
        video_url = urljoin(url, video_url)
        video_path = os.path.join(download_folder, f"{idx}.mp4")

        try:
            print(f"正在从 {video_url} 下载视频 {idx}...")
            video_response = requests.get(video_url, stream=True)
            if video_response.status_code == 200:
                with open(video_path, 'wb') as f:
                    for chunk in video_response.iter_content(chunk_size=1024):
                        f.write(chunk)
                print(f"视频 {idx} 下载成功。")
            else:
                print(f"无法下载视频 {idx}，状态码: {video_response.status_code}")
        except Exception as e:
            print(f"下载视频 {idx} 时出错: {e}")

if __name__ == "__main__":
    # 示例 URL
    website_url = "https://superrobobrain.github.io/"
    download_videos_from_url(website_url)