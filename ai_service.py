# -*- coding: utf-8 -*-
import os, json, re, base64, requests
from datetime import datetime
from PIL import Image

TRACKER_FILE = os.path.join("workspace", "api_tracker.json")
ROOT_TRACKER_FILE = "api_tracker.json"

OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "https://api.ollama.com").rstrip("/")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"

# 🌟 Ollama-তে Gemma মডেলটিকে ১ম প্রায়োরিটি দেওয়া হয়েছে
OLLAMA_MODELS = [
    "gemma4:31b",
    "gemma4",
    "gpt-oss:120b",
    "gpt-oss:20b",
    "nemotron-3-nano:30b",
    "nemotron-3-super",
    "nemotron-3-ultra",
    "kimi-k3",
    "minimax-m3"
]

OPENROUTER_MODELS = [
    "google/gemini-2.5-flash",
    "meta-llama/llama-3.3-70b-instruct",
    "qwen/qwen-2.5-72b-instruct"
]

GROQ_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
CEREBRAS_MODELS = ["llama-3.3-70b", "llama3.1-8b"]

# =========================================================================
# 🌟 API কী পার্সিং ও ট্র্যাকার হেল্পার (Enter / Newline হ্যান্ডলিং)
# =========================================================================

def parse_keys_from_env(*env_names):
    keys = []
    for name in env_names:
        raw_val = os.environ.get(name, "").strip()
        if raw_val:
            for line in re.split(r'[\r\n]+', raw_val):
                clean_k = line.strip()
                if clean_k and not clean_k.startswith('#') and clean_k not in keys:
                    keys.append(clean_k)
    return keys

def load_tracker():
    for path in [TRACKER_FILE, ROOT_TRACKER_FILE]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception: pass
    return {}

def save_tracker_index(service_name, current_idx, total_keys):
    if total_keys == 0: return
    data = load_tracker()
    data[f"{service_name}_idx"] = current_idx % total_keys
    for path in [TRACKER_FILE, ROOT_TRACKER_FILE]:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception: pass

def get_tracker_index(service_name, total_keys):
    if total_keys == 0: return 0
    data = load_tracker()
    return int(data.get(f"{service_name}_idx", 0)) % total_keys

# =========================================================================

DEFAULT_BASE_TAGS = [
    'চাকরির সার্কুলার', 'চাকরির খবর', 'সরকারি চাকরি',
    'job circular', 'govt job circular', 'job application bd'
]

BN_NUMS = {
    0: 'শূন্য', 1: 'এক', 2: 'দুই', 3: 'তিন', 4: 'চার', 5: 'পাঁচ', 6: 'ছয়', 7: 'সাত', 8: 'আট', 9: 'নয়', 10: 'দশ',
    11: 'এগারো', 12: 'বারো', 13: 'তেরো', 14: 'চৌদ্দ', 15: 'পনেরো', 16: 'ষোলো', 17: 'সতেরো', 18: 'আঠারো', 19: 'উনিশ', 20: 'বিশ',
    21: 'একুশ', 22: 'বাইশ', 23: 'তেইশ', 24: 'চব্বিশ', 25: 'পঁচিশ', 26: 'ছাব্বিশ', 27: 'সাতাশ', 28: 'আঠাশ', 29: 'উনত্রিশ', 30: 'ত্রিশ',
    31: 'একত্রিশ', 32: 'বত্রিশ', 33: 'তেত্রিশ', 34: 'চৌত্রিশ', 35: 'পঁয়ত্রিশ', 36: 'ছত্রিশ', 37: 'সাঁইত্রিশ', 38: 'আটত্রিশ', 39: 'উনচল্লিশ', 40: 'চল্লিশ',
    41: 'একচল্লিশ', 42: 'বিয়াল্লিশ', 43: 'তেতাল্লিশ', 44: 'চুয়াল্লিশ', 45: 'পঁয়তাল্লিশ', 46: 'ছেচল্লিশ', 47: 'সাতচল্লিশ', 48: 'আটচল্লিশ', 49: 'উনপঞ্চাশ', 50: 'পঞ্চাশ',
    51: 'একান্ন', 52: 'বায়ান্ন', 53: 'তিপ্পান্ন', 54: 'চুয়ান্ন', 55: 'পঞ্চান্ন', 56: 'ছাপ্পান্ন', 57: 'সাতান্ন', 58: 'আটান্ন', 59: 'উনষাট', 60: 'ষাট',
    61: 'একষট্টি', 62: 'বাষট্টি', 63: 'তেষট্টি', 64: 'চৌষট্টি', 65: 'পঁয়ষট্টি', 66: 'ছেষট্টি', 67: 'সাতষট্টি', 68: 'আটষট্টি', 69: 'উনসত্তর', 70: 'সত্তর',
    71: 'একাত্তর', 72: 'বাহাত্তর', 73: 'তিয়াত্তর', 74: 'চৌহাত্তর', 75: 'পঁচাত্তর', 76: 'ছিয়াত্তর', 77: 'সাতাত্তর', 78: 'আটাত্তর', 79: 'উনআশি', 80: 'আশি',
    81: 'একাশি', 82: 'বিরাশি', 83: 'তিরাশি', 84: 'চুরাশি', 85: 'পঁচাশি', 86: 'ছিয়াশি', 87: 'সাতাশি', 88: 'অষ্টআশি', 89: 'ঊননব্বই', 90: 'নব্বই',
    91: 'একানব্বই', 92: 'বানব্বই', 93: 'তিরানব্বই', 94: 'চুরানব্বই', 95: 'পঁচানব্বই', 96: 'ছিয়ানব্বই', 97: 'সাতানব্বই', 98: 'আটানব্বই', 99: 'নিরানব্বই'
}

DIGIT_TO_ENG_BN = {
    '0': 'জিরো', '1': 'ওয়ান', '2': 'টু', '3': 'থ্রি', '4': 'ফোর',
    '5': 'ফাইভ', '6': 'সিক্স', '7': 'সেভেন', '8': 'এইট', '9': 'নাইন',
    '০': 'জিরো', '১': 'ওয়ান', '২': 'টু', '৩': 'থ্রি', '৪': 'ফোর',
    '৫': 'ফাইভ', '৬': 'সিক্স', '৭': 'সেভেন', '৮': 'এইট', '৯': 'নাইন'
}

def en_bn_to_int(s):
    trans = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
    return int(str(s).translate(trans))

def number_to_bangla_words(n):
    if n == 0: return 'শূন্য'
    parts = []
    koti = n // 10000000
    if koti > 0:
        parts.append(number_to_bangla_words(koti) + ' কোটি')
        n %= 10000000
    lakh = n // 100000
    if lakh > 0:
        parts.append(BN_NUMS.get(lakh, str(lakh)) + ' লাখ')
        n %= 100000
    hajar = n // 1000
    if hajar > 0:
        parts.append(BN_NUMS.get(hajar, str(hajar)) + ' হাজার')
        n %= 1000
    shatok = n // 100
    if shatok > 0:
        if shatok == 1: parts.append('একশত')
        else: parts.append(BN_NUMS.get(shatok, str(shatok)) + ' শত')
        n %= 100
    if n > 0:
        parts.append(BN_NUMS.get(n, str(n)))
    return ' '.join(parts)

def convert_all_numbers_in_script(text):
    if not text: return ""
    text = re.sub(r'(\d+),(\d+)', r'\1\2', text)
    text = re.sub(r'([০-৯]+),([০-৯]+)', r'\1\2', text)

    def phone_repl(m):
        raw_phone = m.group(0)
        digits = re.findall(r'[0-9০-৯]', raw_phone)
        return ' '.join(DIGIT_TO_ENG_BN.get(d, d) for d in digits)

    text = re.sub(r'(\+?(?:88|৮৮)?\s*0?1[0-9০-৯]{8,10})', phone_repl, text)

    def num_repl(m):
        num_str = m.group(0)
        try:
            val = en_bn_to_int(num_str)
            return number_to_bangla_words(val)
        except Exception:
            return num_str

    text = re.sub(r'[0-9০-৯]+', num_repl, text)
    text = re.sub(r'ঘরে\s*বসে\s*', '', text)
    return text

def get_current_years():
    cur_year = datetime.now().year
    en_to_bn = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
    cur_year_bn = str(cur_year).translate(en_to_bn)
    return str(cur_year), cur_year_bn

def normalize_outdated_years(text):
    if not text: return text
    cur_en, cur_bn = get_current_years()
    text = re.sub(r'\b202[0-5]\b', cur_en, str(text))
    text = re.sub(r'২০২[০-৫]', cur_bn, text)
    text = re.sub(r'ঘরে\s*বসে\s*', '', text)
    return text

def sanitize_youtube_tags(raw_tags, max_total_chars=400):
    clean_tags = []
    current_length = 0
    for tag in raw_tags:
        if not tag or not isinstance(tag, str): continue
        cleaned = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[\<\>\"\,\n\r]', '', tag)
        cleaned = normalize_outdated_years(re.sub(r'\s+', ' ', cleaned).strip())
        if not cleaned or len(cleaned) < 2: continue
        cleaned = cleaned[:50].strip()
        if cleaned not in clean_tags:
            tag_len = len(cleaned) + (1 if clean_tags else 0)
            if current_length + tag_len <= max_total_chars:
                clean_tags.append(cleaned)
                current_length += tag_len
            else: break
    return clean_tags

def clean_title_for_display(title):
    clean = title.split('|')[0].split('||')[0].strip()
    return re.sub(r'\s+', ' ', re.sub(r'[\r\n\t]+', ' ', clean))

def strip_unwanted_chars(text):
    cleaned = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|✪|★|☆', '', str(text))
    return normalize_outdated_years(cleaned.strip())

def extract_vacancy_and_qual(title):
    vac_match = re.search(r'(\d+|[০-৯]+)\s*(টি\s*)?পদে', title)
    vac_str = vac_match.group(0) if vac_match else ""
    qual = ""
    if any(k in title.upper() for k in ["SSC", "এসএসসি"]): qual = "SSC পাশ যোগ্যতা"
    elif any(k in title.upper() for k in ["HSC", "এইচএসসি"]): qual = "HSC পাশ যোগ্যতা"
    elif any(k in title for k in ["৮ম", "অষ্টম"]): qual = "৮ম শ্রেণি পাশ"
    elif any(k in title for k in ["স্নাতক", "ডিগ্রী", "অনার্স", "Degree", "Honours"]): qual = "স্নাতক পাশ যোগ্যতা"
    return vac_str, qual

def encode_image_base64(image_path, max_dim=1024):
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            if max(img.size) > max_dim: img.thumbnail((max_dim, max_dim), Image.LANCZOS)
            from io import BytesIO
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception: return None

def parse_json_safely(raw_text):
    try:
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        return json.loads(raw_text)
    except Exception:
        return None

def build_final_response(data, vac_str, qual_str, org_name):
    app_type = data.get("application_type", "online").strip().lower()
    off_reason = data.get("offline_reason", "ডাকযোগে বা সরাসরি আবেদন করতে বলা হয়েছে").strip()

    if app_type == "offline":
        return None, None, None, None, None, "offline", off_reason

    opt_title = normalize_outdated_years(data.get("optimized_title", "").strip()[:100])
    raw_script = normalize_outdated_years(re.sub(r'[\r\n]+', ' ', data.get("voiceover_script", "").strip()))
    script = convert_all_numbers_in_script(raw_script)
    desc = normalize_outdated_years(data.get("video_description", "").strip())
    raw_tags = data.get("specific_tags", []) + DEFAULT_BASE_TAGS
    tags = sanitize_youtube_tags(raw_tags)

    gen_bot = data.get("bot_text", "").strip()
    if not gen_bot or "আবেদনের নিয়ম ও বিস্তারিত" in gen_bot:
        gen_bot = f"({vac_str}) বিশাল সার্কুলার" if vac_str else "আবেদনের শেষ তারিখ ও নিয়ম"

    thumb_meta = {
        "top_text": strip_unwanted_chars(data.get("top_text", org_name)),
        "row1_text": strip_unwanted_chars(data.get("row1_text", "জরুরি নিয়োগ")),
        "row2_text": strip_unwanted_chars(data.get("row2_text", vac_str if vac_str else "বিশাল নিয়োগ")),
        "sub_text": strip_unwanted_chars(data.get("sub_text", qual_str if qual_str else "SSC/HSC পাশ")),
        "bot_text": strip_unwanted_chars(gen_bot)
    }
    return opt_title, script, thumb_meta, desc, tags, "online", ""

# =========================================================================
# 🌟 এআই ইঞ্জিন ক্যাস্কেড (Ollama -> OpenRouter -> Groq -> Cerebras)
# =========================================================================

def generate_job_content(title, img_paths, article_text=""):
    clean_title = clean_title_for_display(title)
    words = clean_title.split()
    org_name = clean_title.split("নিয়োগ")[0].strip() if "নিয়োগ" in clean_title else " ".join(words[:min(3, len(words))])
    vac_str, qual_str = extract_vacancy_and_qual(clean_title)
    snippet_text = article_text[:1800].strip() if article_text else "None provided"

    prompt = f"""You are a professional Bengali YouTube SEO specialist, scriptwriter, and circular inspector.
Context:
- Job Circular Title: "{clean_title}"
- Organization: "{org_name}"
- Scraped Circular Text: "{snippet_text}"

CRITICAL STEP 1 - APPLICATION SUBMISSION INSPECTION:
Carefully inspect both scanned notice images and text:
- Set "application_type": "offline" ONLY IF candidates are required to submit application papers via:
  1. Postal Mail / Post Office (ডাকযোগে / রেজিস্টার্ড ডাকে / ডাক মারফত / ডাকযোগে প্রেরণ)
  2. Courier Service (কুরিয়ারের মাধ্যমে)
  3. Direct Physical In-Person submission (সরাসরি অফিসে গিয়ে / হাতে হাতে জমা দেওয়া)
  And state the reason in "offline_reason" (e.g. "আবেদনপত্র ডাকযোগে পাঠাতে হবে").
- Set "application_type": "online" IF candidates can apply Online (e.g. teletalk.com.bd, web portal, online link, or email).
CAUTION: If circular states 'অনলাইনে আবেদন করতে হবে, ডাকযোগে কোনো আবেদন গ্রহণযোগ্য নয়', that is ONLINE, not offline!

CRITICAL STEP 2 - CONTENT GENERATION (ONLY IF ONLINE):
1. SCRIPT: Exactly 3 minutes (380 to 440 words). Spoken Bengali. No year. Numbers in Bengali words. WhatsApp call to action at end.
2. THUMBNAIL TEXTS:
   - "top_text": 2-3 words. Organization name or Category.
   - "row1_text": 2-3 words. Main Eye-Catching Hook.
   - "row2_text": 2-3 words. Vacancy in RED (e.g. "{vac_str if vac_str else 'বিশাল শূন্যপদ'}").
   - "sub_text": 2-3 words. Specific Qualification / District (e.g. "{qual_str if qual_str else 'SSC/HSC পাশ'}").
   - "bot_text": 2-4 words. DYNAMIC & UNIQUE bottom bar text specifically for this job.

Return strictly valid JSON:
{{
  "application_type": "online" or "offline",
  "offline_reason": "...",
  "optimized_title": "...",
  "voiceover_script": "...",
  "video_description": "...",
  "specific_tags": ["..."],
  "top_text": "...",
  "row1_text": "...",
  "row2_text": "...",
  "sub_text": "...",
  "bot_text": "..."
}}"""

    base64_images = [encode_image_base64(p) for p in img_paths[:3] if encode_image_base64(p)]

    # ------------------ [১ম প্ল্যাটফর্ম: Ollama Cloud (Priority 1)] ------------------
    ollama_keys = parse_keys_from_env("OLLAMA_API_KEYS", "Ollama_API_Key", "OLLAMA_API_KEY")
    total_o = len(ollama_keys)
    if total_o > 0:
        start_idx = get_tracker_index("ollama", total_o)
        for offset in range(total_o):
            cur_idx = (start_idx + offset) % total_o
            key = ollama_keys[cur_idx]
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}

            for model in OLLAMA_MODELS:
                print(f"🤖 [Ollama Key #{cur_idx+1}/{total_o}] Model: '{model}' for '{clean_title[:35]}'...")
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt, "images": base64_images}],
                    "stream": False, "options": {"temperature": 0.4}
                }
                try:
                    resp = requests.post(f"{OLLAMA_API_URL}/api/chat", headers=headers, json=payload, timeout=45)
                    if resp.status_code == 200:
                        raw_c = resp.json().get("message", {}).get("content", "").strip()
                        data = parse_json_safely(raw_c)
                        if data and data.get("optimized_title"):
                            save_tracker_index("ollama", cur_idx, total_o)
                            print(f"✨ [SUCCESS: Ollama Cloud] Verified via Key #{cur_idx+1} ({model})!")
                            return build_final_response(data, vac_str, qual_str, org_name)
                    elif resp.status_code in [401, 403, 429]:
                        print(f"⚠️ Ollama Key #{cur_idx+1} limit reached / unauthorized ({resp.status_code}).")
                        break
                except Exception as e:
                    print(f"⚠️ Ollama network error on Key #{cur_idx+1}: {e}")
                    break

            save_tracker_index("ollama", cur_idx + 1, total_o)

    # ------------------ [২য় প্ল্যাটফর্ম: OpenRouter Cloud (Priority 2)] ------------------
    openrouter_keys = parse_keys_from_env("OPENROUTER_API_KEYS", "OPENROUTER_API_KEY")
    total_or = len(openrouter_keys)
    if total_or > 0:
        print("\n🔄 Switching to OpenRouter Cloud (Priority 2)...")
        start_idx = get_tracker_index("openrouter", total_or)
        for offset in range(total_or):
            cur_idx = (start_idx + offset) % total_or
            key = openrouter_keys[cur_idx]
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com",
                "X-Title": "JobAutomation"
            }

            content_blocks = [{"type": "text", "text": prompt}]
            for b64 in base64_images:
                content_blocks.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

            for model in OPENROUTER_MODELS:
                print(f"🤖 [OpenRouter Key #{cur_idx+1}/{total_or}] Model: '{model}'...")
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": content_blocks}],
                    "temperature": 0.4
                }
                try:
                    resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=45)
                    if resp.status_code == 200:
                        raw_c = resp.json()['choices'][0]['message']['content']
                        data = parse_json_safely(raw_c)
                        if data and data.get("optimized_title"):
                            save_tracker_index("openrouter", cur_idx, total_or)
                            print(f"✨ [SUCCESS: OpenRouter] Verified via Key #{cur_idx+1} ({model})!")
                            return build_final_response(data, vac_str, qual_str, org_name)
                    elif resp.status_code in [401, 402, 429]:
                        print(f"⚠️ OpenRouter Key #{cur_idx+1} exhausted ({resp.status_code}).")
                        break
                except Exception as e:
                    print(f"⚠️ OpenRouter error: {e}")
                    break

            save_tracker_index("openrouter", cur_idx + 1, total_or)

    # ------------------ [৩য় প্ল্যাটফর্ম: Groq Cloud (Priority 3)] ------------------
    groq_keys = parse_keys_from_env("GROQ_API_KEYS", "GROQ_API", "GROQ_API_KEY")
    total_g = len(groq_keys)
    if total_g > 0:
        print("\n🔄 Switching to Groq Cloud (Priority 3)...")
        start_idx = get_tracker_index("groq", total_g)
        for offset in range(total_g):
            cur_idx = (start_idx + offset) % total_g
            key = groq_keys[cur_idx]
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

            for model in GROQ_MODELS:
                print(f"🤖 [Groq Key #{cur_idx+1}/{total_g}] Model: '{model}'...")
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a professional Bengali YouTube SEO and scriptwriter. Output strictly valid JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.4
                }
                try:
                    resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=35)
                    if resp.status_code == 200:
                        raw_c = resp.json()['choices'][0]['message']['content']
                        data = parse_json_safely(raw_c)
                        if data and data.get("optimized_title"):
                            save_tracker_index("groq", cur_idx, total_g)
                            print(f"✨ [SUCCESS: Groq Cloud] Verified via Key #{cur_idx+1} ({model})!")
                            return build_final_response(data, vac_str, qual_str, org_name)
                    elif resp.status_code in [401, 429]:
                        print(f"⚠️ Groq Key #{cur_idx+1} limit reached ({resp.status_code}).")
                        break
                except Exception as e:
                    print(f"⚠️ Groq error: {e}")
                    break

            save_tracker_index("groq", cur_idx + 1, total_g)

    # ------------------ [৪র্থ প্ল্যাটফর্ম: Cerebras Cloud (Priority 4)] ------------------
    cerebras_keys = parse_keys_from_env("CEREBRAS_API_KEYS", "CEREBRAS_API_KEY")
    total_c = len(cerebras_keys)
    if total_c > 0:
        print("\n🔄 Switching to Cerebras Cloud (Priority 4)...")
        start_idx = get_tracker_index("cerebras", total_c)
        for offset in range(total_c):
            cur_idx = (start_idx + offset) % total_c
            key = cerebras_keys[cur_idx]
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

            for model in CEREBRAS_MODELS:
                print(f"🤖 [Cerebras Key #{cur_idx+1}/{total_c}] Model: '{model}'...")
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a professional Bengali YouTube SEO and scriptwriter. Output strictly valid JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.4
                }
                try:
                    resp = requests.post(CEREBRAS_API_URL, headers=headers, json=payload, timeout=35)
                    if resp.status_code == 200:
                        raw_c = resp.json()['choices'][0]['message']['content']
                        data = parse_json_safely(raw_c)
                        if data and data.get("optimized_title"):
                            save_tracker_index("cerebras", cur_idx, total_c)
                            print(f"✨ [SUCCESS: Cerebras Cloud] Verified via Key #{cur_idx+1} ({model})!")
                            return build_final_response(data, vac_str, qual_str, org_name)
                    elif resp.status_code in [401, 429]:
                        print(f"⚠️ Cerebras Key #{cur_idx+1} limit reached ({resp.status_code}).")
                        break
                except Exception as e:
                    print(f"⚠️ Cerebras error: {e}")
                    break

            save_tracker_index("cerebras", cur_idx + 1, total_c)

    return None, None, None, None, None, "error", "All AI platforms exhausted"
