import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

def get_total_pages(soup):
    # Find all page numbers
    page_numbers = soup.find_all("li", class_="pageNav-page")
    if page_numbers:
        # Get the last page number
        last_page = page_numbers[-1].find("a")
        if last_page:
            return int(last_page.text.strip())
        
    return 1

def get_top_comment(url):
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    
    page = 1
    top_comment = {"reacts": 0, "text": "", "link": ""}

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
                        if react_count > top_comment["reacts"]:
                            top_comment["reacts"] = react_count
                            top_comment["text"] = content
                            if "itemid" in post.attrs:
                                top_comment["link"] = post["itemid"]
                            else:
                                top_comment["link"] = full_url + f"#post-{post['data-content']}"
            
            pbar.update(1)
            page += 1
            if page > total_pages:
                break

    return top_comment


# URL chuyên mục Điểm báo
url = "https://voz.vn/f/%C4%90iem-bao.33/"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
}

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

        top_comment = get_top_comment(link)

        print(f"🔥 Title: {title}")
        print(f"Link: {link}")
        print(f"Replies:   {replies}")
        print(f"Top Comment: {top_comment['text']}")
        print(f"Link: {top_comment['link']}")
        print("-" * 80)
else:
    print("Không tìm thấy trending content!")
