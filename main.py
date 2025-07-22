import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from datetime import datetime
import sys
import google.generativeai as genai
import os
from dotenv import load_dotenv
from app import db, News, Comment, AIAnalysis, app as flask_app

# Load environment variables
load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel('gemini-2.0-flash')

def get_total_pages(soup):
    # Find all page numbers
    page_numbers = soup.find_all("li", class_="pageNav-page")
    if page_numbers:
        # Get the last page number
        last_page = page_numbers[-1].find("a")
        if last_page:
            return int(last_page.text.strip())
        
    return 1

def get_top_comments(url, num_comments=5):
    """
    Get top N comments from a VOZ post URL
    Args:
        url (str): URL of the VOZ post
        num_comments (int): Number of top comments to return (default: 5)
    Returns:
        tuple: (news_content, list of comments)
    """
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    
    page = 1
    top_comments = []  # List to store top comments
    news_content = None

    # Get total pages first
    full_url = url
    response = requests.get(full_url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")
    total_pages = get_total_pages(soup)

    # Create progress bar
    with tqdm(total=total_pages, desc="Đang duyệt", unit="trang") as pbar:
        while True:
            full_url = url if page == 1 else url.rstrip("/") + f"/page-{page}"
            response = requests.get(full_url, headers=headers)
            soup = BeautifulSoup(response.text, "html.parser")

            posts = soup.find_all("article", {"class": "message"})
            for post in posts:
                # Get news content from first article
                if page == 1 and news_content is None:
                    content_div = post.find("div", class_="message-content")
                    if content_div:
                        news_content = content_div.get_text(strip=True)

                # Tìm số react
                react_tag = post.find("a", class_="reactionsBar-link")
                if react_tag:
                    reacts_text = react_tag.get_text()
                    # Count visible reactions
                    visible_reacts = len(react_tag.find_all("bdi"))
                    
                    # Count "others" if present
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
                    # Lấy ul.reactionSummary nếu có
                    reaction_ul = post.find("ul", class_="reactionSummary")
                    is_pos = is_positive_comment(reaction_ul)

                    # Lấy ngày đăng comment
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
                        content = content_div.get_text(strip=True)
                        comment = {
                            "reacts": react_count,
                            "text": content,
                            "link": post["itemid"] if "itemid" in post.attrs else full_url + f"#post-{post['data-content']}",
                            "is_positive": is_pos,
                            "date": date_obj
                        }
                        
                        top_comments.append(comment)
            pbar.update(1)
            page += 1
            if page > total_pages:
                break

    # Lấy top N comment theo số react (như cũ)
    filtered_comments = [c for c in top_comments if c["reacts"] > 20]
    if filtered_comments:
        # Nếu có comment > 20 reacts, lấy hết (không giới hạn)
        top_comments = sorted(filtered_comments, key=lambda x: x["reacts"], reverse=True)
    else:
        # Nếu không có, lấy top 5 comment có reacts cao nhất
        top_comments = sorted(top_comments, key=lambda x: x["reacts"], reverse=True)[:num_comments]
    return news_content, top_comments

def analyze_content_with_gemini(news_content, comments):
    """
    Analyze content and comments using Gemini AI
    """
    prompt = """Hãy phân tích nội dung của bài báo dưới đây và kết hợp với các bình luận của độc giả để đưa ra một bản tóm tắt và phân tích đa chiều.

    Tóm tắt ý chính của bài báo (nội dung, lập luận, kết luận).
    
    Tóm tắt các bình luận của độc giả và đưa ra một nhận định tổng quan về chủ đề đang được thảo luận.

    Dưới đây là nội dung bài báo và bình luận:

    Nội dung bài báo:
    {news_content}

    Các bình luận:
    {comments}
    """

    try:
        response = model.generate_content(prompt.format(
            news_content=news_content,
            comments="\n".join([f"Bình luận {i+1} ({c['reacts']} reacts): {c['text']}" for i, c in enumerate(comments)])
        ))
        return response.text
    except Exception as e:
        return f"Error analyzing content with Gemini: {str(e)}"

def process_single_post(url):
    """Process a single VOZ post URL"""
    try:
        news_content, top_comments = get_top_comments(url, num_comments=5)
        # Lấy tiêu đề bài báo (nếu có)
        title = url
        if news_content:
            # Lấy title từ nội dung đầu tiên nếu có
            title = news_content.split(". ")[0][:100]
        # Get AI analysis (TẠM TẮT)
        # ai_analysis = analyze_content_with_gemini(news_content, top_comments)
        # Lưu vào database
        save_news_to_db(url, title, news_content, top_comments, ai_analysis=None)
        # Create output file với timestamp (giữ lại cho debug)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"voz_single_post_{timestamp}.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            # Sắp xếp top_comments theo date trước khi hiển thị
            sorted_comments = sorted(top_comments, key=lambda x: x["date"] or datetime.min)
            f.write(f"News Content from {url}:\n")
            f.write("-" * 80 + "\n")
            f.write(news_content if news_content else "No news content found")
            f.write("\n" + "-" * 80 + "\n")
            f.write("\nTop 5 Comments:\n")
            f.write("-" * 80 + "\n")
            for i, comment in enumerate(sorted_comments, 1):
                date_str = comment["date"].strftime("%Y-%m-%d %H:%M:%S") if comment.get("date") else "N/A"
                f.write(f"\n{i}. Reacts: {comment['reacts']}\n")
                f.write(f"Date: {date_str}\n")
                f.write(f"Comment: {comment['text']}\n")
                f.write(f"Link: {comment['link']}\n")
                f.write("-" * 40 + "\n")
            # f.write("\nAI Analysis:\n")
            # f.write("-" * 80 + "\n")
            # f.write(ai_analysis)
            # f.write("\n" + "-" * 80 + "\n")
        # Also print to console
        print(f"\nNews Content from {url}:")
        print("-" * 80)
        print(news_content if news_content else "No news content found")
        print("-" * 80)
        print(f"\nTop 5 Comments:")
        print("-" * 80)
        # Sắp xếp top_comments theo date trước khi hiển thị
        sorted_comments = sorted(top_comments, key=lambda x: x["date"] or datetime.min)
        for i, comment in enumerate(sorted_comments, 1):
            date_str = comment["date"].strftime("%Y-%m-%d %H:%M:%S") if comment.get("date") else "N/A"
            print(f"\n{i}. Reacts: {comment['reacts']}")
            print(f"Date: {date_str}")
            print(f"Comment: {comment['text']}")
            print(f"Link: {comment['link']}")
            print("-" * 40)
        # print("\nAI Analysis:")
        # print("-" * 80)
        # print(ai_analysis)
        # print("-" * 80)
        print(f"\nResults have been saved to {output_file}")
    except Exception as e:
        print(f"Error processing URL: {e}")

def process_trending_posts():
    """Process trending posts from the main page"""
    url = "https://voz.vn/f/%C4%90iem-bao.33/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"voz_trending_{timestamp}.txt"
    with open(output_file, "w", encoding="utf-8") as f:
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
                news_content, top_comments = get_top_comments(link, num_comments=4)
                # ai_analysis = analyze_content_with_gemini(news_content, top_comments)  # TẠM TẮT
                # Lưu vào database
                save_news_to_db(link, title, news_content, top_comments, ai_analysis=None)
                f.write(f"🔥 Title: {title}\n")
                f.write(f"Link: {link}\n")
                f.write(f"Replies:   {replies}\n")
                f.write("\nNews Content:\n")
                f.write(news_content if news_content else "No news content found")
                f.write("\n\nTop 4 Comments:\n")
                for i, comment in enumerate(top_comments, 1):
                    f.write(f"\n{i}. Reacts: {comment['reacts']}\n")
                    f.write(f"Comment: {comment['text']}\n")
                    f.write(f"Link: {comment['link']}\n")
                # f.write("\nAI Analysis:\n")
                # f.write("-" * 80 + "\n")
                # f.write(ai_analysis)
                # f.write("\n" + "-" * 80 + "\n")
        else:
            f.write("Không tìm thấy trending content!\n")
    print(f"Results have been saved to {output_file}")

def save_news_to_db(url, title, news_content, comments, ai_analysis):
    with flask_app.app_context():
        # Kiểm tra đã có bài này chưa
        news = News.query.filter_by(url=url).first()
        if not news:
            news = News(url=url, title=title, content=news_content)
            db.session.add(news)
            db.session.commit()
        # Xóa comment cũ (nếu có)
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
        # Lưu AI analysis (TẠM TẮT)
        # if news.ai_analysis:
        #     news.ai_analysis.analysis = ai_analysis
        # else:
        #     db.session.add(AIAnalysis(news_id=news.id, analysis=ai_analysis))
        db.session.commit()

def is_positive_comment(reaction_ul):
    """
    Trả về True nếu reaction 'Ưng' xuất hiện đầu tiên, False nếu 'Gạch' đầu tiên, None nếu không xác định.
    reaction_ul: Tag <ul class="reactionSummary">
    """
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

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # If URL is provided as command line argument, process that URL
        post_url = sys.argv[1]
        process_single_post(post_url)
    else:
        # Otherwise process trending posts
        process_trending_posts()
