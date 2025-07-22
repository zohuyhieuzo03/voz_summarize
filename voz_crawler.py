import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from datetime import datetime
import google.generativeai as genai
import os
from dotenv import load_dotenv
import re
from urllib.parse import urlparse, parse_qs, unquote

# Load environment variables
load_dotenv()

genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel('gemini-2.0-flash')

def get_total_pages(soup):
    page_numbers = soup.find_all("li", class_="pageNav-page")
    if page_numbers:
        last_page = page_numbers[-1].find("a")
        if last_page:
            return int(last_page.text.strip())
    return 1

def get_top_comments(url, num_comments=5, progress_callback=None):
    # Chỉ lấy phần đầu url đến dạng voz.vn/t/...
    match = re.match(r"^(https?://voz.vn/t/[^/]+\.\d+)", url)
    if match:
        url = match.group(1)
    headers = {"User-Agent": "Mozilla/5.0"}
    page = 1
    top_comments = []
    news_content = None
    news_title = None
    full_url = url
    response = requests.get(full_url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")
    total_pages = get_total_pages(soup)
    # Lấy title từ <h1 class="p-title-value">
    title_tag = soup.find("h1", class_="p-title-value")
    if title_tag:
        news_title = title_tag.get_text(strip=True)
    if progress_callback:
        progress_callback(0, total_pages)
    while True:
        full_url = url if page == 1 else url.rstrip("/") + f"/page-{page}"
        response = requests.get(full_url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        posts = soup.find_all("article", {"class": "message"})
        for post in posts:
            if page == 1 and news_content is None:
                content_div = post.find("div", class_="message-content")
                if content_div:
                    # Sửa ảnh proxy thành link gốc
                    html = content_div.decode_contents()
                    soup2 = BeautifulSoup(html, "html.parser")
                    for img in soup2.find_all("img"):
                        if img.has_attr("data-url") and img["data-url"]:
                            img["src"] = img["data-url"]
                        elif img.has_attr("data-src") and img["data-src"]:
                            img["src"] = img["data-src"]
                        elif img.has_attr("src"):
                            src = img["src"]
                            if src.startswith("/proxy.php"):
                                qs = parse_qs(urlparse(src).query)
                                if "url" in qs:
                                    img["src"] = unquote(qs["url"][0])
                            elif src.startswith("/attachments/"):
                                img["src"] = "https://voz.vn" + src
                    news_content = str(soup2)
            react_tag = post.find("a", class_="reactionsBar-link")
            if react_tag:
                reacts_text = react_tag.get_text()
                visible_reacts = len(react_tag.find_all("bdi"))
                if "and" in reacts_text and "others" in reacts_text:
                    others_text = reacts_text.split("and")[1].split("others")[0].strip()
                    try:
                        others_count = int(others_text)
                        react_count = visible_reacts + others_count
                    except ValueError:
                        react_count = visible_reacts
                else:
                    react_count = visible_reacts
                content_div = post.find("div", class_="message-content")
                reaction_ul = post.find("ul", class_="reactionSummary")
                is_pos = is_positive_comment(reaction_ul)
                date_str = None
                date_obj = None
                time_tag = post.find("time", class_="u-dt")
                if time_tag and time_tag.has_attr("datetime"):
                    date_str = time_tag["datetime"]
                    try:
                        date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    except Exception:
                        date_obj = None
                if content_div:
                    html = content_div.decode_contents()
                    soup2 = BeautifulSoup(html, "html.parser")
                    for img in soup2.find_all("img"):
                        if img.has_attr("data-url") and img["data-url"]:
                            img["src"] = img["data-url"]
                        elif img.has_attr("data-src") and img["data-src"]:
                            img["src"] = img["data-src"]
                        elif img.has_attr("src"):
                            src = img["src"]
                            if src.startswith("/proxy.php"):
                                qs = parse_qs(urlparse(src).query)
                                if "url" in qs:
                                    img["src"] = unquote(qs["url"][0])
                            elif src.startswith("/attachments/"):
                                img["src"] = "https://voz.vn" + src
                    content = str(soup2)
                    comment = {
                        "reacts": react_count,
                        "text": content,
                        "link": post["itemid"] if "itemid" in post.attrs else full_url + f"#post-{post['data-content']}",
                        "is_positive": is_pos,
                        "date": date_obj
                    }
                    top_comments.append(comment)
        if progress_callback:
            progress_callback(page, total_pages)
        page += 1
        if page > total_pages:
            break
    top_comments.sort(key=lambda x: x["reacts"], reverse=True)
    # count number of comment that react > 20
    num_comments_over_20 = len([c for c in top_comments if c["reacts"] > 20])
    get_number = max(num_comments, num_comments_over_20)
    top_comments = top_comments[:get_number]

    return news_title, news_content, top_comments

def analyze_content_with_gemini(news_content, comments):
    prompt = """Hãy phân tích nội dung của bài báo dưới đây và kết hợp với các bình luận của độc giả để đưa ra một bản tóm tắt và phân tích đa chiều.\n\n    Tóm tắt ý chính của bài báo (nội dung, lập luận, kết luận).\n    \n    Tóm tắt các bình luận của độc giả và đưa ra một nhận định tổng quan về chủ đề đang được thảo luận.\n\n    Dưới đây là nội dung bài báo và bình luận:\n\n    Nội dung bài báo:\n    {news_content}\n\n    Các bình luận:\n    {comments}\n    """
    try:
        response = model.generate_content(prompt.format(
            news_content=news_content,
            comments="\n".join([f"Bình luận {i+1} ({c['reacts']} reacts): {c['text']}" for i, c in enumerate(comments)])
        ))
        return response.text
    except Exception as e:
        return f"Error analyzing content with Gemini: {str(e)}"

def process_single_post(url, db, News, Comment, AIAnalysis, flask_app, progress_callback=None):
    try:
        news_title, news_content, top_comments = get_top_comments(url, num_comments=5, progress_callback=progress_callback)
        title = news_title if news_title else url
        save_news_to_db(url, title, news_content, top_comments, ai_analysis=None, db=db, News=News, Comment=Comment, AIAnalysis=AIAnalysis, flask_app=flask_app)
    except Exception as e:
        print(f"Error processing URL: {e}")

def process_trending_posts(db, News, Comment, AIAnalysis, flask_app):
    url = "https://voz.vn/f/%C4%90iem-bao.33/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    trending_block = soup.find("div", {"data-widget-key": "forum_view__trending_content"})
    if trending_block:
        items = trending_block.find_all("li", class_="block-row")
        for item in items:
            title_tag = item.find("div", class_="contentRow-main").find("a")
            title = title_tag.text.strip()
            link = "https://voz.vn" + title_tag.get("href")
            replies_tag = item.find("div", class_="contentRow-minor", string=lambda text: text and "Replies:" in text)
            if replies_tag:
                replies_text = replies_tag.get_text(strip=True)
                replies = replies_text.replace("Replies:", "").strip()
            else:
                replies = "0"
            news_content, top_comments = get_top_comments(link, num_comments=5)
            save_news_to_db(link, title, news_content, top_comments, ai_analysis=None, db=db, News=News, Comment=Comment, AIAnalysis=AIAnalysis, flask_app=flask_app)
    else:
        print("Không tìm thấy trending content!")

def save_news_to_db(url, title, news_content, comments, ai_analysis, db, News, Comment, AIAnalysis, flask_app):
    with flask_app.app_context():
        news = News.query.filter_by(url=url).first()
        if not news:
            news = News(url=url, title=title, content=news_content)
            db.session.add(news)
            db.session.commit()
        Comment.query.filter_by(news_id=news.id).delete()
        for c in comments:
            comment = Comment(
                news_id=news.id,
                reacts=c['reacts'],
                text=c['text'],
                link=c['link'],
                is_positive=c.get('is_positive'),
                created_at=c.get('date') if c.get('date') else None
            )
            db.session.add(comment)
        db.session.commit()

def is_positive_comment(reaction_ul):
    if not reaction_ul:
        return None
    imgs = reaction_ul.find_all("img", class_="reaction-image")
    if not imgs:
        return None
    first_title = imgs[0].get("title")
    if first_title == "Ưng":
        return True
    if first_title == "Gạch":
        return False
    return None 