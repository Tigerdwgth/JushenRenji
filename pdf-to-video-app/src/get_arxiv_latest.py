from bs4 import BeautifulSoup
from dataclasses import dataclass
import feedparser
import datetime
import requests
import datetime

@dataclass
class Paper:
    title: str
    authors: list
    abstract: str
    link: str
    announced_date: str
    submitted_date: str
    comments: str = ""  # 保留 comments 字段

def get_latest_embodied_ai_papers(amount=100, query="embodied+AI+robot", date=""):
    # 使用 arXiv API 获取数据
    response = feedparser.parse(f"https://export.arxiv.org/api/query?search_query=all:{query}&sortBy=lastUpdatedDate&sortOrder=descending&max_results={amount}")
    papers = []
    
    for entry in response.entries:
        # 如果没有 comments 字段，设置为空字符串
        comments = entry.arxiv_comment if hasattr(entry, "arxiv_comment") else ""
        paper = Paper(
            title=entry.title,
            authors=[author.name for author in entry.authors],
            abstract=entry.summary,
            link=entry.link,
            announced_date=entry.published,
            submitted_date=entry.updated,
            comments=comments
        )
        papers.append(paper)
    
    # 过滤日期
    if date:
        papers = [paper for paper in papers if datetime.datetime.strptime(paper.submitted_date, "%Y-%m-%dT%H:%M:%SZ") >= datetime.datetime.strptime(date, "%Y-%m-%d")]
    
    return papers

def get_paper_from_arxiv(query="cs.RO"):
    # 使用 HTML 页面解析方式获取数据
    url = f"https://arxiv.org/search/?searchtype=all&query={query}&abstracts=show&size=200&order=-announced_date_first"
    response = requests.get(url)
    
    if response.status_code != 200:
        print(f"Failed to fetch data from arXiv. Status code: {response.status_code}")
        return []

    html_content = response.text
    papers = parse_arxiv_html(html_content)
    return papers

def parse_arxiv_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    papers = []

    # 找到所有论文条目
    for result in soup.find_all('li', class_='arxiv-result'):
        # 提取标题
        title_tag = result.find('p', class_='title')
        title = title_tag.get_text(strip=True) if title_tag else "N/A"

        # 提取作者
        authors_tag = result.find('p', class_='authors')
        authors = [a.get_text(strip=True) for a in authors_tag.find_all('a')] if authors_tag else []

        # 提取摘要
        abstract_tag = result.find('span', class_='abstract-short')
        abstract = abstract_tag.get_text(strip=True) if abstract_tag else "N/A"

        # 提取提交日期和公告日期
        submitted_tag = result.find('p', class_='is-size-7')
        if submitted_tag:
            submitted_text = submitted_tag.get_text(strip=True)
            submitted_date_raw = submitted_text.split(';')[0].replace('Submitted', '').strip()
            announced_date_raw = submitted_text.split(';')[1].replace('announced', '').strip() if len(submitted_text.split(';')) > 1 else "N/A"

            # 转换日期格式
            submitted_date = convert_date_format(submitted_date_raw)
            announced_date = convert_date_format(announced_date_raw)
        else:
            submitted_date = "N/A"
            announced_date = "N/A"

        # 提取链接
        link_tag = result.find('a', href=True)
        link = link_tag['href'] if link_tag else "N/A"

        # 提取 comments
        comments_tag = result.find('p', class_='comments')
        comments = comments_tag.get_text(strip=True) if comments_tag else "N/A"

        # 创建 Paper 对象并添加到列表中
        paper = Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            link=link,
            announced_date=announced_date,
            submitted_date=submitted_date,
            comments=comments
        )
        papers.append(paper)

    return papers

def convert_date_format(date_str):
    """
    将日期字符串5 April, 2025转换为统一的格式：%Y-%m-%d
    如果无法解析，则返回原始字符串。
    """
    try:
        # 尝试解析常见的日期格式
        for fmt in ["%d %B, %Y", "%B %d, %Y", "%Y-%m-%d"]:
            try:
                parsed_date = datetime.datetime.strptime(date_str, fmt)
                return parsed_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                continue
        # 如果所有格式都无法解析，返回原始字符串
        return date_str
    except Exception as e:
        print(f"日期解析失败: {date_str}, 错误: {e}")
        return date_str

#filter by date

def filter_papers_by_date(papers, date=datetime.datetime.now().strftime("%Y-%m-%d")):
    filtered_papers = []
    for paper in papers:
        # print(f"Submitted date: {paper.submitted_date}")
        # print(f"Date: {date}")
        if datetime.datetime.strptime(paper.submitted_date, "%Y-%m-%dT%H:%M:%SZ") >= datetime.datetime.strptime(date, "%Y-%m-%d"):
            filtered_papers.append(paper)
    return filtered_papers
if __name__ == "__main__":
    #using arxiv api
    papers = get_latest_embodied_ai_papers()
    for i, paper in enumerate(papers, 1):
        print(f"Paper {i}:")
        print(f"Title: {paper.title}")
        print(f"Authors: {', '.join(paper.authors)}")
        print(f"Published: {paper.announced_date}")
        print(f"Link: {paper.link}")
        #print(f"Summary: {paper.abstract}\n")
    #using curl command to get the latest paper
    #https://arxiv.org/search/?searchtype=all&query=cs.RO&abstracts=show&size=200&order=-announced_date_first
    papers = get_paper_from_arxiv()
    for i, paper in enumerate(papers, 1):
        print(f"Paper {i}:")
        print(f"Title: {paper.title}")
        print(f"Authors: {', '.join(paper.authors)}")
        #print(f"Published: {paper.announced_date}")
        print(f"Link: {paper.link}")
        print(f"Comments: {paper.comments}")
        print(f"Submitted: {paper.submitted_date}")
        if i >= 5:
            break   
        #print(f"Summary: {paper.abstract}\n")