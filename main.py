import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from datetime import datetime
import sys
import google.generativeai as genai
import os
from dotenv import load_dotenv

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
                    if content_div:
                        content = content_div.get_text(strip=True)
                        comment = {
                            "reacts": react_count,
                            "text": content,
                            "link": post["itemid"] if "itemid" in post.attrs else full_url + f"#post-{post['data-content']}"
                        }
                        
                        # Add comment to list and keep only top N
                        top_comments.append(comment)
                        top_comments.sort(key=lambda x: x["reacts"], reverse=True)
                        top_comments = top_comments[:num_comments]
            
            pbar.update(1)
            page += 1
            if page > total_pages:
                break

    return news_content, top_comments

def analyze_content_with_gemini(news_content, comments):
    """
    Analyze content and comments using Gemini AI
    """
    prompt = """Hãy phân tích nội dung của bài báo dưới đây và kết hợp với các bình luận của độc giả để đưa ra một bản tóm tắt và phân tích đa chiều.

Tóm tắt ý chính của bài báo (nội dung, lập luận, kết luận).

Nhận diện các quan điểm chính từ phần bình luận (đồng tình, phản biện, bổ sung, quan sát mới).

So sánh giữa quan điểm của tác giả và của người đọc, chỉ ra các điểm tương đồng, khác biệt hoặc mâu thuẫn nếu có.

Cuối cùng, đưa ra một nhận định tổng quan về chủ đề đang được thảo luận.

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
        
        # Get AI analysis
        ai_analysis = analyze_content_with_gemini(news_content, top_comments)
        
        # Create output file with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"voz_single_post_{timestamp}.txt"
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"News Content from {url}:\n")
            f.write("-" * 80 + "\n")
            f.write(news_content if news_content else "No news content found")
            f.write("\n" + "-" * 80 + "\n")
            
            f.write("\nTop 5 Comments:\n")
            f.write("-" * 80 + "\n")
            for i, comment in enumerate(top_comments, 1):
                f.write(f"\n{i}. Reacts: {comment['reacts']}\n")
                f.write(f"Comment: {comment['text']}\n")
                f.write(f"Link: {comment['link']}\n")
                f.write("-" * 40 + "\n")
            
            f.write("\nAI Analysis:\n")
            f.write("-" * 80 + "\n")
            f.write(ai_analysis)
            f.write("\n" + "-" * 80 + "\n")
        
        # Also print to console
        print(f"\nNews Content from {url}:")
        print("-" * 80)
        print(news_content if news_content else "No news content found")
        print("-" * 80)
        
        print(f"\nTop 5 Comments:")
        print("-" * 80)
        for i, comment in enumerate(top_comments, 1):
            print(f"\n{i}. Reacts: {comment['reacts']}")
            print(f"Comment: {comment['text']}")
            print(f"Link: {comment['link']}")
            print("-" * 40)
        
        print("\nAI Analysis:")
        print("-" * 80)
        print(ai_analysis)
        print("-" * 80)
            
        print(f"\nResults have been saved to {output_file}")
    except Exception as e:
        print(f"Error processing URL: {e}")

def process_trending_posts():
    """Process trending posts from the main page"""
    # URL chuyên mục Điểm báo
    url = "https://voz.vn/f/%C4%90iem-bao.33/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    # Create output file with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"voz_trending_{timestamp}.txt"

    with open(output_file, "w", encoding="utf-8") as f:
        # Gửi request
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, "html.parser")

        # Tìm trending content block
        trending_block = soup.find("div", {"data-widget-key": "forum_view__trending_content"})

        if trending_block:
            items = trending_block.find_all("li", class_="block-row")
            
            for item in items:
                title_tag = item.find("div", class_="contentRow-main").find("a")
                title = title_tag.text.strip()
                link = "https://voz.vn" + title_tag.get("href")
                
                # Tìm số replies
                replies_tag = item.find("div", class_="contentRow-minor", string=lambda text: text and "Replies:" in text)
                if replies_tag:
                    replies_text = replies_tag.get_text(strip=True)
                    replies = replies_text.replace("Replies:", "").strip()
                else:
                    replies = "0"

                news_content, top_comments = get_top_comments(link, num_comments=4)
                
                # Get AI analysis
                ai_analysis = analyze_content_with_gemini(news_content, top_comments)

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
                f.write("\nAI Analysis:\n")
                f.write("-" * 80 + "\n")
                f.write(ai_analysis)
                f.write("\n" + "-" * 80 + "\n")
        else:
            f.write("Không tìm thấy trending content!\n")

    print(f"Results have been saved to {output_file}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # If URL is provided as command line argument, process that URL
        post_url = sys.argv[1]
        process_single_post(post_url)
    else:
        # Otherwise process trending posts
        process_trending_posts()
