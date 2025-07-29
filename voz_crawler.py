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
                    for img in soup2.find_all("img"):
                        img["style"] = "max-width:400px; height:auto;"  # hoặc img["width"] = "400"
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
    prompt = """Hãy phân tích nội dung của bài báo dưới đây và kết hợp với các bình luận của độc giả để đưa ra một bản tóm tắt và phân tích đa chiều.

**Yêu cầu:**
- Sử dụng định dạng Markdown để trình bày
- Tạo các tiêu đề rõ ràng với ##
- Sử dụng danh sách có dấu đầu dòng (-) cho các điểm chính
- Sử dụng **bold** cho các từ khóa quan trọng
- Sử dụng > cho các trích dẫn đặc biệt

**Cấu trúc phân tích:**

## 📰 Tóm tắt bài báo
- Nội dung chính
- Lập luận và kết luận

## 💬 Phân tích bình luận cộng đồng
- Tổng quan các ý kiến
- Nhận định về chủ đề

## 🔍 Kết luận tổng quan
- Đánh giá tổng thể về chủ đề

Dưới đây là nội dung bài báo và bình luận:

**Nội dung bài báo:**
{news_content}

**Các bình luận:**
{comments}"""
    try:
        response = model.generate_content(prompt.format(
            news_content=news_content,
            comments="\n".join([f"Bình luận {i+1} ({c['reacts']} reacts): {c['text']}" for i, c in enumerate(comments)])
        ))
        return response.text
    except Exception as e:
        return f"Error analyzing content with Gemini: {str(e)}"

def get_comments_for_ai_analysis(url, db, Comment, news_id):
    """
    Lấy tất cả comments để phân tích AI (không giới hạn số lượng)
    """
    # Lấy tất cả comments hiện có trong database
    existing_comments = Comment.query.filter_by(news_id=news_id).all()
    
    # Luôn crawl thêm comments để đảm bảo có đầy đủ
    try:
        # Crawl tất cả comments có thể (không giới hạn số lượng)
        news_title, news_content, additional_comments = get_top_comments(url, num_comments=10000)
        
        # Lấy các link comment đã có trong DB
        existing_links = set(c.link for c in existing_comments)
        
        # Thêm comments mới vào database
        for c in additional_comments:
            if c['link'] not in existing_links:
                comment = Comment(
                    news_id=news_id,
                    reacts=c['reacts'],
                    text=c['text'],
                    link=c['link'],
                    is_positive=c.get('is_positive'),
                    created_at=c.get('date') if c.get('date') else None
                )
                db.session.add(comment)
        
        db.session.commit()
        
        # Lấy lại tất cả comments sau khi thêm mới
        all_comments = Comment.query.filter_by(news_id=news_id).all()
        return all_comments
    except Exception as e:
        print(f"Error crawling additional comments for AI analysis: {e}")
        return existing_comments

def get_display_comments(db, Comment, news_id):
    """
    Lấy comments để hiển thị theo rule cũ:
    - Top 5 comments theo react, sort theo date
    - Nếu có >5 comments với >20 react thì lấy hết
    """
    # Lấy tất cả comments từ database
    all_comments = Comment.query.filter_by(news_id=news_id).all()
    
    # Lọc comments có >20 react
    high_react_comments = [c for c in all_comments if c.reacts and c.reacts > 20]
    
    # Nếu có >5 comments với >20 react, lấy tất cả comments có >20 react
    if len(high_react_comments) > 5:
        # Sort theo date (oldest first)
        display_comments = sorted(high_react_comments, key=lambda c: c.created_at or datetime.min)
    else:
        # Lấy top 5 comments theo react, sort theo date
        sorted_comments = sorted(all_comments, key=lambda c: (c.reacts or 0, c.created_at or datetime.min), reverse=True)
        display_comments = sorted_comments[:5]
        # Sort lại theo date (oldest first)
        display_comments = sorted(display_comments, key=lambda c: c.created_at or datetime.min)
    
    return display_comments

def truncate_text(text, max_length=8000):
    """
    Cắt text nếu quá dài, giữ lại phần đầu và cuối
    """
    if len(text) <= max_length:
        return text
    
    # Cắt ở giữa, giữ lại 70% đầu và 30% cuối
    first_part = int(max_length * 0.7)
    last_part = max_length - first_part
    
    return text[:first_part] + "\n\n[... nội dung bị cắt ...]\n\n" + text[-last_part:]

def chunk_comments_for_ai(comments, max_comments_per_chunk=200, max_chars_per_comment=2000):
    """
    Chia comments thành các chunk nhỏ hơn để xử lý
    """
    chunks = []
    current_chunk = []
    current_length = 0
    
    for i, comment in enumerate(comments):
        # Xử lý cả comment object và dict
        if hasattr(comment, 'reacts'):
            reacts = comment.reacts
            text = comment.text
            link = comment.link
        else:
            reacts = comment.get('reacts', 0)
            text = comment.get('text', '')
            link = comment.get('link', '')
        
        # Cắt text comment nếu quá dài
        if len(text) > max_chars_per_comment:
            text = truncate_text(text, max_chars_per_comment)
        
        comment_text = f"\nBình luận {i+1} ({reacts} reacts) - Link: {link}:\n{text}\n"
        comment_length = len(comment_text)
        
        # Nếu thêm comment này vượt quá giới hạn hoặc đã đủ số lượng
        if (current_length + comment_length > 15000) or len(current_chunk) >= max_comments_per_chunk:
            if current_chunk:  # Lưu chunk hiện tại
                chunks.append(current_chunk)
                current_chunk = []
                current_length = 0
        
        current_chunk.append(comment)
        current_length += comment_length
    
    # Thêm chunk cuối cùng
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks

def chat_with_ai_about_thread(title, content, comments, question, url=None, db=None, Comment=None, news_id=None):
    """
    Chat với AI về một thread cụ thể dựa trên title, content và comments
    """
    # Nếu có thông tin database, lấy comments để phân tích AI
    if url and db and Comment and news_id:
        ai_comments = get_comments_for_ai_analysis(url, db, Comment, news_id)
        comments = ai_comments
    
    # Cắt content nếu quá dài
    content = truncate_text(content, 5000)
    
    # Chia comments thành chunks
    comment_chunks = chunk_comments_for_ai(comments)
    
    # Nếu chỉ có 1 chunk hoặc ít comments, xử lý bình thường
    if len(comment_chunks) <= 1:
        thread_context = f"""
        Tiêu đề thread: {title}
        
        Nội dung chính:
        {content}
        
        Các bình luận từ cộng đồng (tổng cộng {len(comments)} bình luận):
        """
        
        # Thêm comments vào context với link
        for i, comment in enumerate(comments):
            if hasattr(comment, 'reacts'):
                reacts = comment.reacts
                text = comment.text
                link = comment.link
            else:
                reacts = comment.get('reacts', 0)
                text = comment.get('text', '')
                link = comment.get('link', '')
            
            # Cắt text comment nếu quá dài
            if len(text) > 2000:
                text = truncate_text(text, 2000)
            
            thread_context += f"\nBình luận {i+1} ({reacts} reacts) - Link: {link}:\n{text}\n"
        
        return process_single_chunk(title, content, thread_context, question, len(comments))
    
    # Nếu có nhiều chunks, xử lý từng chunk và tổng hợp
    else:
        return process_multiple_chunks(title, content, comment_chunks, question, len(comments))

def process_single_chunk(title, content, thread_context, question, total_comments):
    """
    Xử lý một chunk duy nhất
    """
    prompt = f"""
    Bạn là một AI assistant chuyên phân tích và trả lời câu hỏi về các thread trên diễn đàn VOZ.
    
    Dưới đây là thông tin về một thread cụ thể:
    
    {thread_context}
    
    Câu hỏi của người dùng: {question}
    
    **Yêu cầu trả lời:**
    - Sử dụng định dạng Markdown để trình bày
    - Tạo các tiêu đề rõ ràng với ##
    - Sử dụng danh sách có dấu đầu dòng (-) cho các điểm chính
    - Sử dụng **bold** cho các từ khóa quan trọng
    - Sử dụng > cho các trích dẫn từ bình luận cụ thể
    - Sử dụng `code` cho các thuật ngữ kỹ thuật
    - **Khi trích dẫn comment:** Sử dụng format: > [Nội dung comment](Link comment)
    
    Hãy trả lời câu hỏi dựa trên thông tin từ thread trên. Nếu câu hỏi liên quan đến:
    - **Sản phẩm/dịch vụ:** Hãy phân tích các ý kiến, đánh giá, khuyến nghị từ cộng đồng
    - **Sự kiện/tin tức:** Hãy tóm tắt và phân tích các góc nhìn khác nhau
    - **Kinh nghiệm/cách làm:** Hãy tổng hợp các chia sẻ thực tế từ người dùng
    - **So sánh/lựa chọn:** Hãy đưa ra phân tích dựa trên các ý kiến trong thread
    
    Trả lời bằng tiếng Việt, rõ ràng và có cấu trúc. Nếu có thể, hãy trích dẫn các bình luận cụ thể để minh họa.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text, total_comments
    except Exception as e:
        return f"Lỗi khi xử lý câu hỏi: {str(e)}", 0

def process_multiple_chunks(title, content, comment_chunks, question, total_comments):
    """
    Xử lý nhiều chunks và tổng hợp kết quả
    """
    try:
        # Xử lý từng chunk
        chunk_analyses = []
        
        for i, chunk in enumerate(comment_chunks):
            chunk_context = f"""
            Tiêu đề thread: {title}
            
            Nội dung chính:
            {content}
            
            Phần bình luận {i+1}/{len(comment_chunks)} (từ comment {i*50+1} đến {i*50+len(chunk)}):
            """
            
            # Thêm comments của chunk này
            for j, comment in enumerate(chunk):
                if hasattr(comment, 'reacts'):
                    reacts = comment.reacts
                    text = comment.text
                    link = comment.link
                else:
                    reacts = comment.get('reacts', 0)
                    text = comment.get('text', '')
                    link = comment.get('link', '')
                
                # Cắt text comment nếu quá dài
                if len(text) > 2000:
                    text = truncate_text(text, 2000)
                
                chunk_context += f"\nBình luận {i*200+j+1} ({reacts} reacts) - Link: {link}:\n{text}\n"
            
            # Phân tích chunk này
            chunk_prompt = f"""
            Bạn là một AI assistant chuyên phân tích và trả lời câu hỏi về các thread trên diễn đàn VOZ.
            
            {chunk_context}
            
            Câu hỏi của người dùng: {question}
            
            Hãy phân tích phần bình luận này và đưa ra những điểm chính liên quan đến câu hỏi.
            Trả lời ngắn gọn, tập trung vào những thông tin quan trọng nhất.
            """
            
            response = model.generate_content(chunk_prompt)
            chunk_analyses.append(response.text)
        
        # Tổng hợp kết quả từ tất cả chunks
        summary_prompt = f"""
        Bạn là một AI assistant chuyên tổng hợp và phân tích thông tin.
        
        Dưới đây là các phân tích từ {len(comment_chunks)} phần khác nhau của một thread VOZ:
        
        {chr(10).join([f"**Phần {i+1}:**{chr(10)}{analysis}" for i, analysis in enumerate(chunk_analyses)])}
        
        Câu hỏi của người dùng: {question}
        
        **Yêu cầu:**
        - Tổng hợp tất cả thông tin trên thành một câu trả lời hoàn chỉnh
        - Sử dụng định dạng Markdown để trình bày
        - Tạo các tiêu đề rõ ràng với ##
        - Sử dụng danh sách có dấu đầu dòng (-) cho các điểm chính
        - Sử dụng **bold** cho các từ khóa quan trọng
        - Sử dụng > cho các trích dẫn từ bình luận cụ thể
        - Sử dụng `code` cho các thuật ngữ kỹ thuật
        - **Khi trích dẫn comment:** Sử dụng format: > [Nội dung comment](Link comment)
        
        Trả lời bằng tiếng Việt, rõ ràng và có cấu trúc. Tổng hợp thông tin từ tất cả các phần để đưa ra câu trả lời toàn diện.
        """
        
        final_response = model.generate_content(summary_prompt)
        return final_response.text, total_comments
        
    except Exception as e:
        return f"Lỗi khi xử lý câu hỏi: {str(e)}", 0

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
        print(f"DEBUG: Saving URL to DB: {url}")
        news = News.query.filter_by(url=url).first()
        if not news:
            news = News(url=url, title=title, content=news_content)
            db.session.add(news)
            db.session.commit()
            print(f"DEBUG: Created new news entry with URL: {url}")
        else:
            print(f"DEBUG: Found existing news entry with URL: {url}")
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

def get_forum_threads(News, db, flask_app=None):
    url = "https://voz.vn/f/%C4%90iem-bao.33/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    list_threads = soup.find("div", class_="js-threadList")
    
    if list_threads:
        # Get all processed URLs from database
        processed_urls = set()
        if flask_app:
            with flask_app.app_context():
                processed_news = News.query.all()
                for news in processed_news:
                    processed_urls.add(news.url)
                print(f"DEBUG: Processed URLs in DB: {processed_urls}")
        
        # Debug: Print the HTML structure to see what we're working with
        print(f"DEBUG: HTML structure preview: {str(list_threads)[:500]}...")
        
        # Try different selectors to find thread items
        thread_items = list_threads.find_all("li", class_="structItem")
        if not thread_items:
            thread_items = list_threads.find_all("div", class_="structItem")
        if not thread_items:
            thread_items = list_threads.find_all("article", class_="structItem")
        if not thread_items:
            thread_items = list_threads.find_all("div", class_="structItem--thread")
        if not thread_items:
            thread_items = list_threads.find_all("li")  # Any li elements
        if not thread_items:
            thread_items = list_threads.find_all("div")  # Any div elements
            
        print(f"DEBUG: Found {len(thread_items)} thread items")
        if thread_items:
            print(f"DEBUG: First item classes: {thread_items[0].get('class', [])}")
            print(f"DEBUG: First item HTML: {str(thread_items[0])[:300]}...")
        
        # Extract thread items with their reply counts for sorting
        thread_data = []
        for item in thread_items:
            # Try different ways to find the title link - focus on thread links, not user links
            title_link = None
            
            # Look for the main thread link
            main_cell = item.find("div", class_="structItem-cell--main")
            if main_cell:
                # Find the thread title link
                title_link = main_cell.find("a", class_="fauxBlockLink-link")
                if not title_link:
                    title_link = main_cell.find("a", class_="structItem-title")
                if not title_link:
                    # Look for any link that contains /t/ (thread pattern)
                    all_links = main_cell.find_all("a", href=True)
                    for link in all_links:
                        href = link.get("href", "")
                        if "/t/" in href and not href.startswith("/u/"):
                            title_link = link
                            break
            
            if title_link:
                thread_url = "https://voz.vn" + title_link.get("href")
                print(f"DEBUG: Checking thread URL: {thread_url}")
                print(f"DEBUG: Is in processed_urls? {thread_url in processed_urls}")
                
                # Get reply count
                reply_count = 0
                meta_cell = item.find("div", class_="structItem-cell--meta")
                if meta_cell:
                    # Look for reply count in various formats
                    reply_text = meta_cell.get_text()
                    # Try to extract number from text like "Replies: 123" or "123 replies"
                    import re
                    reply_match = re.search(r'(\d+)', reply_text)
                    if reply_match:
                        reply_count = int(reply_match.group(1))
                
                thread_data.append({
                    'item': item,
                    'url': thread_url,
                    'reply_count': reply_count,
                    'is_processed': thread_url in processed_urls
                })
            else:
                print(f"DEBUG: Could not find title link in item")
                # Debug: print all links in this item
                all_links = item.find_all("a", href=True)
                for link in all_links:
                    href = link.get("href", "")
                    print(f"DEBUG: Found link: {href}")
        
        # Sort by reply count (descending)
        thread_data.sort(key=lambda x: x['reply_count'], reverse=True)
        
        # Clear the original list and add sorted items
        list_threads.clear()
        for thread_info in thread_data:
            item = thread_info['item']
            
            # Mark as processed if needed
            if thread_info['is_processed']:
                print(f"DEBUG: Marking as processed: {thread_info['url']}")
                # Add processed indicator
                processed_indicator = soup.new_tag("div")
                processed_indicator["style"] = "background: #4caf50; color: white; padding: 2px 6px; border-radius: 3px; font-size: 10px; margin-top: 4px; display: inline-block;"
                processed_indicator.string = "✓ Đã xử lý"
                
                # Add to the title area
                title_cell = item.find("div", class_="structItem-cell--main")
                if title_cell:
                    title_cell.append(processed_indicator)
                
                # Also fade the entire item
                if "style" in item.attrs:
                    item["style"] += "; opacity: 0.6;"
                else:
                    item["style"] = "opacity: 0.6;"
            
            # Add reply count indicator
            reply_indicator = soup.new_tag("div")
            reply_indicator["style"] = "background: #007bff; color: white; padding: 2px 6px; border-radius: 3px; font-size: 10px; margin-top: 4px; display: inline-block; margin-left: 8px;"
            reply_indicator.string = f"💬 {thread_info['reply_count']}"
            
            # Add to the title area
            title_cell = item.find("div", class_="structItem-cell--main")
            if title_cell:
                title_cell.append(reply_indicator)
            
            list_threads.append(item)
        
        return str(list_threads)
    return "" 