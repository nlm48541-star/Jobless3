# -*- coding: utf-8 -*-
import os, json, time, re, requests, feedparser
from datetime import datetime, timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup

WORKSPACE_DIR = "workspace"
FORBIDDEN_KEYWORDS = ['এনজিও', 'ngo', 'ব্যাংক', 'bank', 'চলমান']

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
}

def is_forbidden_article(text):
    if not text: return False
    t_lower = text.lower()
    return any(k in t_lower for k in FORBIDDEN_KEYWORDS)

def clean_filename(text):
    text = re.sub(r'[\\/*?:"<>|]', "", str(text))
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:90]

def clean_article_text(raw_html):
    if not raw_html: return ""
    soup = BeautifulSoup(raw_html, 'html.parser')
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r'\s+', ' ', text)[:3500]

def extract_image_urls_from_html(html_content, base_url=""):
    if not html_content: return []
    soup = BeautifulSoup(html_content, 'html.parser')
    img_urls = []
    
    containers = soup.find_all(['div', 'article', 'section'], class_=re.compile(r'(post-body|entry-content|post-content|article-body|td-post-content|main-content)', re.I))
    elements = containers if containers else [soup]

    for container in elements:
        for img in container.find_all('img'):
            src = (
                img.get('data-original') or img.get('data-src') or 
                img.get('data-lazy-src') or img.get('data-orig-file') or img.get('src')
            )
            if not src and img.get('srcset'):
                src = img.get('srcset').split(',')[0].split()[0]

            if src:
                src = src.strip()
                if base_url: src = urljoin(base_url, src)
                src_lower = src.lower()
                if any(ext in src_lower for ext in ['.jpg', '.jpeg', '.png', '.webp']) or 'uploads' in src_lower:
                    if not any(bad in src_lower for bad in ['logo', 'avatar', 'gravatar', 'icon', 'emoji', 'share', 'button']):
                        if src.startswith("http") and src not in img_urls:
                            img_urls.append(src)
    return img_urls

def scrape_article_content_and_images(page_url):
    """ওয়েবপেজ থেকে আর্টিকেলের টাইটেল, মূল টেক্সট এবং ইমেজ লিংক সংগ্রহ করে"""
    try:
        req_headers = HEADERS.copy()
        req_headers["Referer"] = page_url
        resp = requests.get(page_url, headers=req_headers, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = soup.find('title').get_text().strip() if soup.find('title') else ""
            txt = clean_article_text(resp.text)
            imgs = extract_image_urls_from_html(resp.text, base_url=page_url)
            return title, txt, imgs
    except Exception as e:
        print(f"⚠️ Scraping error on {page_url}: {e}")
    return "", "", []

def download_image(url, output_path, referer_url=""):
    try:
        req_headers = HEADERS.copy()
        if referer_url: req_headers["Referer"] = referer_url
        req = requests.get(url, headers=req_headers, timeout=15)
        if req.status_code == 200 and len(req.content) > 3000:
            with open(output_path, 'wb') as f:
                f.write(req.content)
            return True
    except Exception: pass
    return False

def check_new_articles_and_prepare_folders():
    print("Checking for new RSS items (Last 24 Hours)...")
    if not os.path.exists(WORKSPACE_DIR): os.makedirs(WORKSPACE_DIR)
    if not os.path.exists('config.json'): return

    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            rss_links = config_data.get('rss_links', [])
    except Exception: return

    time_limit = datetime.now() - timedelta(hours=24)
    existing = [f for f in os.listdir(WORKSPACE_DIR) if os.path.isdir(os.path.join(WORKSPACE_DIR, f))]
    
    history_file = os.path.join(WORKSPACE_DIR, "history.txt")
    history_logs = set()
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as hf:
                history_logs = {line.strip().lower() for line in hf if line.strip()}
        except Exception: pass

    for feed_url in rss_links:
        try:
            resp = requests.get(feed_url, headers=HEADERS, timeout=15)
            feed = feedparser.parse(resp.content) if resp.status_code == 200 else feedparser.parse(feed_url)
        except Exception: continue
        
        for entry in feed.entries:
            try: published_time = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            except Exception: continue

            if published_time >= time_limit:
                raw_title = entry.title.strip()
                folder_title = clean_filename(raw_title).strip()
                link = entry.get('link', '').strip()

                if folder_title.lower() == "shorts" or not folder_title or folder_title in existing: continue
                if link.lower() in history_logs or raw_title.lower() in history_logs or folder_title.lower() in history_logs: continue
                if is_forbidden_article(raw_title) or is_forbidden_article(folder_title): continue

                content = entry.content[0].value if hasattr(entry, 'content') else getattr(entry, 'summary', "")
                article_text = clean_article_text(content)
                valid_img_urls = extract_image_urls_from_html(content, base_url=link)

                if (not valid_img_urls or len(article_text) < 100) and link:
                    _, web_text, web_imgs = scrape_article_content_and_images(link)
                    if not valid_img_urls: valid_img_urls = web_imgs
                    if len(web_text) > len(article_text): article_text = web_text

                if not valid_img_urls: continue

                folder_path = os.path.join(WORKSPACE_DIR, folder_title)
                os.makedirs(folder_path, exist_ok=True)
                
                downloaded_temp_files = []
                for idx, src in enumerate(valid_img_urls[:5], start=1):
                    temp_img_path = os.path.join(folder_path, f"temp_{idx}.jpg")
                    if download_image(src, temp_img_path, referer_url=link):
                        downloaded_temp_files.append(temp_img_path)

                if not downloaded_temp_files:
                    shutil.rmtree(folder_path, ignore_errors=True)
                    continue

                for final_idx, temp_path in enumerate(downloaded_temp_files, start=1):
                    try: os.rename(temp_path, os.path.join(folder_path, f"{final_idx}.jpg"))
                    except Exception: pass

                with open(os.path.join(folder_path, "title.txt"), "w", encoding="utf-8") as tf:
                    tf.write(raw_title)
                if link:
                    with open(os.path.join(folder_path, "link.txt"), "w", encoding="utf-8") as lf:
                        lf.write(link)
                # 🌟 আর্টিকেলের লেখা সেভ করা (এআই এটি পড়ে স্ক্রিপ্ট লিখবে)
                if article_text:
                    with open(os.path.join(folder_path, "article.txt"), "w", encoding="utf-8") as af:
                        af.write(article_text)

                print(f"✅ Prepared Article: {folder_title}")
                existing.append(folder_title)
