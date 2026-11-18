# -*- coding: utf-8 -*-
import os, json, time, re, shutil, requests, feedparser
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, NavigableString
from PIL import Image

WORKSPACE_DIR = "workspace"
FORBIDDEN_KEYWORDS = ['এনজিও', 'ngo', 'ব্যাংক', 'bank', 'চলমান']

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
}

NOISE_SELECTOR_RE = re.compile(
    r'(sidebar|widget|toc|table-of-contents|ez-toc|lwptoc|rank-math-toc|faq|accordion|'
    r'related|recent-posts|popular-posts|author-box|comment|share|social|newsletter|'
    r'disclaimer|calculator|breadcrumb|wp-post-image|post-thumbnail|featured-image|'
    r'page-header-image|entry-header|post-meta|entry-meta|entry-footer|navigation|'
    r'nav-links|yarpp|crp_related|jp-relatedposts|heateor|addtoany|sharedaddy)',
    re.I,
)

BAD_IMG_RE = re.compile(
    r'(logo|avatar|gravatar|icon|emoji|share|button|badge|qrcode|qr-code|favicon|'
    r'ads|promo|author|whatsapp|telegram|facebook|messenger|placeholder|'
    r'150x150|300x169|300x200|wp-content/themes|\.svg(?:\?|$)|\.gif(?:\?|$))',
    re.I,
)

CIRCULAR_SECTION_RE = re.compile(
    r'(images\s*/\s*pdfs?|pdf\s*/\s*ছবি|পিডিএফ\s*/\s*ইমেজ|সার্কুলার(?:ের)?\s*ছবি|'
    r'অফিশিয়াল\s*নিয়োগ\s*বিজ্ঞপ্তি\s*pdf|অফিশিয়াল\s*বিজ্ঞপ্তি)',
    re.I,
)

INLINE_RELATED_HEADING_RE = re.compile(
    r'^(?:আরো\s*দেখুন|আরও\s*দেখুন|আরো\s*দেখতে\s*পারেন|আরও\s*দেখতে\s*পারেন|দেখে\s*নিন)\s*[-–—:ঃ]?',
    re.I,
)

SKIP_SECTION_HEADING_RE = re.compile(
    r'(বেতনস্কেল\s*ও\s*সম্ভাব্য|কাদের\s*জন্য.*সেরা\s*সুযোগ|প্রস্তুতি\s*ও\s*এক্সপার্ট\s*টিপস|'
    r'প্রতিষ্ঠান\s*সম্পর্কে\s*জ্ঞান|ভুল\s*তথ্য\s*সমাধান|ডিক্লারেশন\s*\(declaration\)|'
    r'সকল\s*নির্দেশনা|মৌখিক\s*পরীক্ষার\s*শর্ত|আবেদনের\s*শর্ত|'
    r'নতুন\s*চাকরির\s*নিয়োগ\s*বিজ্ঞপ্তি\s*বিষয়ে\s*আরো|গুরুত্বপূর্ণ\s*সতর্কতা)',
    re.I,
)

STOP_MARKERS = [
    "সাধারণ জিজ্ঞাসা (FAQ)",
    "সাধারণ জিজ্ঞাসা",
    "আরও চলমান নিয়োগ",
    "আরও অন্যান্য চাকরির নিয়োগ বিজ্ঞপ্তি",
    "নিচে সাম্প্রতিক আরও নিয়োগ বিজ্ঞপ্তি",
    "সর্বশেষ প্রকাশিত",
    "গত ৭ দিনের জনপ্রিয়",
    "শীঘ্রই আবেদন শেষ",
    "লিখেছেন ও যাচাই করেছেন",
    "আমাদের সম্পর্কে",
    "নিয়মিত চাকরির আপডেট পান",
    "সবার আগে নতুন চাকরির আপডেট পেতে",
    "Share this post:",
    "Your email address will not be published",
    "Leave a Comment",
]


def _get_site_type(url):
    host = urlparse(str(url or "")).netloc.lower()
    if "bdgovtjob.net" in host:
        return "bdgovtjob"
    if "bdgovtnotice.com" in host:
        return "bdgovtnotice"
    if "projobsbd.com" in host:
        return "projobsbd"
    return "generic"


def is_forbidden_article(text):
    if not text:
        return False
    return any(k in str(text).lower() for k in FORBIDDEN_KEYWORDS)


def clean_filename(text):
    text = re.sub(r'[\\/*?:"<>|]', "", str(text))
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:90]


def _pick_real_img_src(img_tag, base_url=""):
    """WordPress Lazy-Load (data-lazy-src, data-src) আগে চেক করে এবং ডামি data:image/svg+xml বাদ দেয়"""
    cls = " ".join(img_tag.get('class', [])) if isinstance(img_tag.get('class'), list) else str(img_tag.get('class', ''))
    if 'wp-post-image' in cls.lower():
        return None

    candidates = [
        img_tag.get('data-lazy-src'),
        img_tag.get('data-src'),
        img_tag.get('data-original'),
        img_tag.get('data-orig-file'),
        img_tag.get('data-full-url'),
        img_tag.get('data-large_image'),
    ]
    for attr in ('data-lazy-srcset', 'data-srcset', 'srcset'):
        ss = img_tag.get(attr)
        if ss:
            parts = [p.strip().split()[0] for p in ss.split(',') if p.strip()]
            if parts:
                candidates.append(parts[-1])
    candidates.append(img_tag.get('src'))

    for raw in candidates:
        if not raw:
            continue
        url = str(raw).strip()
        if not url or url.startswith('data:'):
            continue
        if base_url:
            url = urljoin(base_url, url)
        u_lower = url.lower()
        if not u_lower.startswith('http'):
            continue
        if BAD_IMG_RE.search(u_lower):
            continue
        if any(ext in u_lower for ext in ('.jpg', '.jpeg', '.png', '.webp')) or 'uploads' in u_lower or 'googleusercontent' in u_lower:
            return url
    return None


def _pick_main_container(soup):
    selectors = [
        ('div', re.compile(r'\b(entry-content|post-content|post-body|article-body|td-post-content)\b', re.I)),
        ('article', None),
        ('main', None),
    ]
    for tag_name, cls_re in selectors:
        found = soup.find(tag_name, class_=cls_re) if cls_re else soup.find(tag_name)
        if found:
            return found
    return soup


def _strip_noise_elements(container):
    for tag in container(['script', 'style', 'noscript', 'nav', 'footer', 'header', 'aside', 'form', 'iframe', 'svg']):
        tag.decompose()
    for el in list(container.find_all(['div', 'section', 'ul', 'nav', 'figure'])):
        if not getattr(el, 'attrs', None):
            continue
        cls = " ".join(el.get('class', [])) if isinstance(el.get('class'), list) else str(el.get('class', ''))
        eid = str(el.get('id', ''))
        if NOISE_SELECTOR_RE.search(f"{cls} {eid}"):
            el.decompose()


def _remove_inline_related_blocks(container):
    """projobsbd.com-এর পেটের ভেতরের 'আরো দেখুন-' / 'আরো দেখতে পারেন-' লিংক ব্লকগুলো পরিষ্কারভাবে মুছে দেয়"""
    for el in list(container.find_all(['p', 'h2', 'h3', 'h4', 'div', 'strong', 'b'])):
        if not el.parent:
            continue
        txt = re.sub(r'\s+', ' ', el.get_text(" ", strip=True))
        if not txt or len(txt) > 160:
            continue
        if INLINE_RELATED_HEADING_RE.search(txt):
            nxt = el.find_next_sibling()
            removed_list = 0
            while nxt and removed_list < 6:
                following = nxt.find_next_sibling()
                if nxt.name in ('ul', 'ol'):
                    nxt.decompose()
                    break
                elif nxt.name in ('p', 'div'):
                    links = nxt.find_all('a')
                    nxt_txt = nxt.get_text(" ", strip=True)
                    if links and len(nxt_txt) <= 280 and not any(k in nxt_txt for k in ['আবেদনের নিয়ম', 'আবেদনপত্র', 'বয়স']):
                        nxt.decompose()
                        removed_list += 1
                        nxt = following
                        continue
                    else:
                        break
                else:
                    break
            if el.name in ('p', 'h2', 'h3', 'h4', 'div'):
                el.decompose()


def _collect_imgs_from_tag(tag, base_url):
    urls = []
    for img in tag.find_all('img'):
        parent_a = img.find_parent('a')
        if parent_a and parent_a.get('href'):
            href = urljoin(base_url, parent_a.get('href').strip())
            if any(ext in href.lower() for ext in ('.jpg', '.jpeg', '.png', '.webp')) and not BAD_IMG_RE.search(href):
                if href not in urls:
                    urls.append(href)
                continue
        real_url = _pick_real_img_src(img, base_url=base_url)
        if real_url and real_url not in urls:
            urls.append(real_url)
    return urls


def extract_image_urls_from_html(html_content, base_url=""):
    if not html_content:
        return []
    site_type = _get_site_type(base_url)
    soup = BeautifulSoup(html_content, 'html.parser')
    container = _pick_main_container(soup)
    _strip_noise_elements(container)
    _remove_inline_related_blocks(container)

    # bdgovtjob.net ও bdgovtnotice.com-এ আসল সার্কুলার ছবি নির্দিষ্ট হেডিংয়ের নিচে থাকে (ওপরের কভার ব্যানার বাদ দিতে)
    if site_type in ("bdgovtjob", "bdgovtnotice"):
        section_imgs = []
        for heading in container.find_all(['h2', 'h3', 'h4']):
            htxt = heading.get_text(" ", strip=True)
            if CIRCULAR_SECTION_RE.search(htxt):
                sib = heading.find_next_sibling()
                while sib:
                    if sib.name in ('h2',) or (sib.name in ('h3', 'h4') and any(m in sib.get_text(" ", strip=True) for m in STOP_MARKERS)):
                        break
                    for u in _collect_imgs_from_tag(sib, base_url):
                        if u not in section_imgs:
                            section_imgs.append(u)
                    sib = sib.find_next_sibling()
                if section_imgs:
                    return section_imgs

    return _collect_imgs_from_tag(container, base_url)


def _clean_article_text(container, site_type="generic"):
    for h in container.find_all(['h2', 'h3', 'h4']):
        htxt = re.sub(r'\s+', ' ', h.get_text(" ", strip=True))
        if htxt:
            h.replace_with(NavigableString(f"\n\n### {htxt}\n"))

    for li in container.find_all('li'):
        ltxt = re.sub(r'\s+', ' ', li.get_text(" ", strip=True))
        if ltxt:
            li.replace_with(NavigableString(f"\n- {ltxt}"))

    for table in container.find_all('table'):
        rows_txt = []
        for tr in table.find_all('tr'):
            cells = [re.sub(r'\s+', ' ', c.get_text(" ", strip=True)) for c in tr.find_all(['th', 'td'])]
            cells = [c for c in cells if c]
            if cells:
                rows_txt.append(" | ".join(cells))
        table.replace_with(NavigableString("\n" + "\n".join(rows_txt) + "\n"))

    raw_text = container.get_text(separator='\n', strip=True)

    lines = []
    skip_section = False
    for line in raw_text.splitlines():
        s = line.strip()
        if not s:
            continue
        if any(marker in s for marker in STOP_MARKERS):
            break

        if s.startswith("### "):
            heading_body = s[4:].strip()
            if SKIP_SECTION_HEADING_RE.search(heading_body):
                skip_section = True
                continue
            else:
                skip_section = False

        if skip_section:
            continue

        if s in ("সংরক্ষণ করুন", "সংরক্ষিত", "ট্র্যাক করুন", "আবেদন করবো", "আবেদন করেছি", "পরীক্ষা/ভাইভা", "আর্কাইভ", "সকল তথ্যের টেবিল", "পদের বিবরণ", "সার্কুলারের ছবি", "Join WhatsApp Channel"):
            continue
        lines.append(s)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()

    if site_type == "projobsbd" and cleaned:
        cleaned = (
            "[SOURCE_HINT: projobsbd.com — এই সাইটে কখনো কখনো পুরনো টেক্সট নিচে থাকে বা একই পোস্টে একাধিক জেলার সার্কুলার থাকে; "
            "তাই সংযুক্ত সার্কুলার ছবিই চূড়ান্ত সত্য হিসেবে ধরবে।]\n\n" + cleaned
        )
    elif site_type == "bdgovtnotice" and cleaned:
        cleaned = (
            "[SOURCE_HINT: bdgovtnotice.com — এই সাইটের পদ-তালিকা সাধারণত সংযুক্ত সার্কুলার ছবিতেই থাকে।]\n\n" + cleaned
        )
    return cleaned


def scrape_article_content_and_images(page_url):
    """
    🌟 bdgovtnotice.com, bdgovtjob.net, projobsbd.com থেকে সাইট-ভিত্তিক Lazy-Load ছবি ও পরিষ্কার স্ট্রাকচার্ড টেক্সট সংগ্রহ করে
    """
    title = ""
    clean_text = ""
    img_urls = []
    site_type = _get_site_type(page_url)

    try:
        req_headers = HEADERS.copy()
        req_headers["Referer"] = page_url
        resp = requests.get(page_url, headers=req_headers, timeout=22)
        if resp.status_code == 200:
            if 'charset' not in resp.headers.get('content-type', '').lower():
                resp.encoding = resp.apparent_encoding or 'utf-8'

            img_urls = extract_image_urls_from_html(resp.text, base_url=page_url)

            soup = BeautifulSoup(resp.text, 'html.parser')
            h1 = soup.find('h1')
            if h1:
                title = h1.get_text(" ", strip=True)
            elif soup.title:
                title = soup.title.get_text(" ", strip=True).split('-')[0].split('|')[0].strip()

            target = _pick_main_container(soup)
            _strip_noise_elements(target)
            _remove_inline_related_blocks(target)
            clean_text = _clean_article_text(target, site_type=site_type)
    except Exception as e:
        print(f"⚠️ Error scraping article: {e}")
    return title, clean_text, img_urls


def download_image(url, output_path, referer_url=""):
    try:
        req_headers = HEADERS.copy()
        if referer_url:
            req_headers["Referer"] = referer_url
        req = requests.get(url, headers=req_headers, timeout=22)
        if req.status_code == 200 and len(req.content) > 8000:
            with open(output_path, 'wb') as f:
                f.write(req.content)
            with Image.open(output_path) as im:
                w, h = im.size
                if w < 450 or h < 350:
                    os.remove(output_path)
                    return False
                im.convert("RGB").save(output_path, "JPEG", quality=92)
            return True
    except Exception:
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
    return False


def _entry_has_forbidden_category(entry):
    tags = getattr(entry, 'tags', None) or []
    cat_text = " ".join(str(t.get('term', '')) for t in tags if isinstance(t, dict)).lower()
    if any(k in cat_text for k in ['এনজিও', 'ngo', 'ব্যাংক', 'bank', 'চলমান বিজ্ঞপ্তি']):
        return True
    return False


def check_new_articles_and_prepare_folders():
    print("Checking for new RSS items (Last 24 Hours)...")
    if not os.path.exists(WORKSPACE_DIR):
        os.makedirs(WORKSPACE_DIR)
    if not os.path.exists('config.json'):
        return

    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            rss_links = json.load(f).get('rss_links', [])
    except Exception:
        return

    time_limit = datetime.now() - timedelta(hours=24)
    existing = [f for f in os.listdir(WORKSPACE_DIR) if os.path.isdir(os.path.join(WORKSPACE_DIR, f))]

    history_file = os.path.join(WORKSPACE_DIR, "history.txt")
    history_logs = set()
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as hf:
                history_logs = {line.strip().lower() for line in hf if line.strip()}
        except Exception:
            pass

    for feed_url in rss_links:
        try:
            resp = requests.get(feed_url, headers=HEADERS, timeout=20)
            feed = feedparser.parse(resp.content) if resp.status_code == 200 else feedparser.parse(feed_url)
        except Exception:
            continue

        for entry in feed.entries:
            try:
                published_time = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            except Exception:
                continue

            if published_time >= time_limit:
                raw_title = entry.title.strip()
                folder_title = clean_filename(raw_title).strip()
                link = entry.get('link', '').strip()

                if folder_title.lower() == "shorts" or not folder_title or folder_title in existing:
                    continue
                if link.lower() in history_logs or raw_title.lower() in history_logs or folder_title.lower() in history_logs:
                    continue
                if is_forbidden_article(raw_title) or is_forbidden_article(folder_title) or _entry_has_forbidden_category(entry):
                    print(f"🚫 [FILTERED] Skipping '{folder_title}'.")
                    continue

                scraped_title, article_text, img_urls = scrape_article_content_and_images(link) if link else ("", "", [])

                if not img_urls or len(article_text) < 120:
                    rss_html = entry.content[0].value if hasattr(entry, 'content') else getattr(entry, 'summary', "")
                    if rss_html:
                        if not img_urls:
                            img_urls = extract_image_urls_from_html(rss_html, base_url=link)
                        if len(article_text) < 120:
                            soup_rss = BeautifulSoup(rss_html, 'html.parser')
                            _strip_noise_elements(soup_rss)
                            _remove_inline_related_blocks(soup_rss)
                            rss_text = _clean_article_text(soup_rss, site_type=_get_site_type(link))
                            if len(rss_text) > len(article_text):
                                article_text = rss_text

                if not img_urls:
                    print(f"⏩ Skipping '{folder_title}' (No valid circular images found).")
                    continue

                folder_path = os.path.join(WORKSPACE_DIR, folder_title)
                os.makedirs(folder_path, exist_ok=True)

                downloaded_info = []
                for idx, src in enumerate(img_urls, start=1):
                    temp_img_path = os.path.join(folder_path, f"temp_{idx}.jpg")
                    if download_image(src, temp_img_path, referer_url=link):
                        try:
                            with Image.open(temp_img_path) as im:
                                w, h = im.size
                            downloaded_info.append((temp_img_path, w, h, w / float(h)))
                        except Exception:
                            pass

                if not downloaded_info:
                    shutil.rmtree(folder_path, ignore_errors=True)
                    continue

                # ব্লগের ডেকোরেটিভ ল্যান্ডস্কেপ কভার ব্যানার (ratio >= 1.32) বাদ দিয়ে আসল সার্কুলার ছবি রাখা
                non_banners = [item for item in downloaded_info if item[3] < 1.32]
                if non_banners:
                    for item in downloaded_info:
                        if item[3] >= 1.32:
                            try:
                                os.remove(item[0])
                                print(f"✂️ [Cover Banner Removed] Dropped blog banner ({item[1]}x{item[2]}).")
                            except Exception:
                                pass
                    kept_files = [item[0] for item in non_banners]
                else:
                    best = max(downloaded_info, key=lambda x: x[1] * x[2])
                    for item in downloaded_info:
                        if item[0] != best[0]:
                            try:
                                os.remove(item[0])
                            except Exception:
                                pass
                    kept_files = [best[0]]

                final_img_count = 0
                for final_idx, temp_path in enumerate(kept_files, start=1):
                    final_path = os.path.join(folder_path, f"{final_idx}.jpg")
                    try:
                        os.rename(temp_path, final_path)
                        final_img_count += 1
                    except Exception:
                        pass

                if final_img_count == 0:
                    shutil.rmtree(folder_path, ignore_errors=True)
                    continue

                with open(os.path.join(folder_path, "title.txt"), "w", encoding="utf-8") as tf:
                    tf.write(raw_title)
                if link:
                    with open(os.path.join(folder_path, "link.txt"), "w", encoding="utf-8") as lf:
                        lf.write(link)
                if article_text:
                    with open(os.path.join(folder_path, "article.txt"), "w", encoding="utf-8") as af:
                        af.write(article_text)

                print(f"✅ Prepared Article: {folder_title} ({final_img_count} Circular Image(s), {len(article_text)} Chars)")
                existing.append(folder_title)
