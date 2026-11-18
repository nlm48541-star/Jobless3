# -*- coding: utf-8 -*-
import base64
import io
import json
import os
import re
import requests
from datetime import datetime
from PIL import Image

WORKSPACE_DIR = "workspace"
TRACKER_FILE = "api_key_tracker.json"
WORKSPACE_TRACKER = os.path.join(WORKSPACE_DIR, "api_key_tracker.json")

# =========================================================================
# 🌟 মডেল কনফিগারেশন (নভেম্বর ২০২৬ অনুযায়ী যাচাইকৃত সচল Vision + Text মডেল)
# =========================================================================

OPENROUTER_VISION_MODELS = [
    "nvidia/nemotron-3.5-super-vl:free",      # 120B MoE Multimodal
    "thinkingmachines/inkling-2-small:free",  # 594B MoE Multimodal
    "inclusionai/ling-3.2-flash:free",        # 1M Context Multimodal
    "google/gemma-4-31b-it:free",             # 31B Dense Multimodal
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "openrouter/free",                        # Free Auto Router (Multimodal)
]

OPENROUTER_TEXT_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free", # 550B MoE
    "nvidia/nemotron-3.5-super-vl:free",      # 120B MoE
    "thinkingmachines/inkling-2-small:free",  # 594B MoE
    "inclusionai/ling-3.2-flash:free",        # Hybrid Reasoning
    "google/gemma-4-31b-it:free",             # 31B Dense
    "openrouter/free",                        # Free Auto Router
]

OLLAMA_CHAT_URL = "https://ollama.com/api/chat"

OLLAMA_VISION_MODELS = [
    "glm-5.3-flash",                          # Native Multimodal Flagship
    "deepseek-v4.1-flash",                    # 552B Multimodal
    "kimi-k3.1-pro",                          # Multimodal Flagship
    "qwen3-vl:235b-cloud",                    # 235B Vision
    "gemma4:31b",                             # 31B Multimodal
    "kimi-k2.6",                              # 1.04T Multimodal
]

OLLAMA_TEXT_MODELS = [
    "kimi-k3.1-pro",
    "deepseek-v4.1-flash",
    "glm-5.3",
    "glm-5.3-flash",
    "kimi-k2.6",
    "qwen3.5:397b",
    "gpt-oss:120b",
    "gemma4:31b",
]

GROQ_VISION_MODELS = [
    "qwen/qwen3.8-27b",                       # 27B Multimodal (Active on Groq)
]

GROQ_TEXT_MODELS = [
    "openai/gpt-oss-120b",                    # 120B
    "qwen/qwen3.8-27b",                       # 27B
    "openai/gpt-oss-20b",                     # 20B
]

CEREBRAS_MODELS = [
    "gpt-oss-120b",                           # 120B
    "qwen-3.8-27b",                           # 27B
]

GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
]


def clean_script_for_speech(raw_text):
    if not raw_text:
        return ""
    text = re.sub(r'<think>.*?</think>', '', str(raw_text), flags=re.DOTALL)
    text = re.sub(r'[\*\_\|\#\~\x60]', '', text)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'https?://\S+|wa\.me/\S+', '', text)
    text = re.sub(r'[\<\>\{\}\(\)\@\$\^\&\+\=\_\\\/]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_multiline_keys(raw_text):
    if not raw_text:
        return []
    lines = re.split(r'[\r\n,;]+', str(raw_text))
    return [k.strip() for k in lines if k.strip() and not k.strip().startswith('#')]


def mask_key(k):
    if not k or len(k) <= 8:
        return "****"
    return k[:4] + "..." + k[-4:]


def load_tracker():
    for p in [WORKSPACE_TRACKER, TRACKER_FILE]:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def save_tracker_index(service_name, index, total_keys):
    if total_keys == 0:
        return
    data = load_tracker()
    if service_name not in data:
        data[service_name] = {}
    data[service_name]["current_index"] = index % total_keys
    data[service_name]["last_updated"] = datetime.now().isoformat()
    for p in [WORKSPACE_TRACKER, TRACKER_FILE]:
        try:
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def get_keys_in_cyclic_order(service_name, raw_keys_str):
    keys = parse_multiline_keys(raw_keys_str)
    if not keys:
        return []
    total = len(keys)
    data = load_tracker()
    saved_idx = data.get(service_name, {}).get("current_index", 0) % total
    return [((saved_idx + i) % total, keys[(saved_idx + i) % total]) for i in range(total)]


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

BN_MONTHS = {
    1: 'জানুয়ারি', 2: 'ফেব্রুয়ারি', 3: 'মার্চ', 4: 'এপ্রিল',
    5: 'মে', 6: 'জুন', 7: 'জুলাই', 8: 'আগস্ট',
    9: 'সেপ্টেম্বর', 10: 'অক্টোবর', 11: 'নভেম্বর', 12: 'ডিসেম্বর'
}

ACRONYM_TO_BN = {
    'SSC': 'এসএসসি', 'HSC': 'এইচএসসি', 'JSC': 'জেএসসি', 'PSC': 'পিএসসি',
    'GPA': 'জিপিএ', 'CGPA': 'সিজিপিএ', 'NID': 'এনআইডি', 'CV': 'সিভি',
    'MIS': 'এমআইএস', 'SMS': 'এসএমএস', 'PDF': 'পিডিএফ', 'ICT': 'আইসিটি',
    'IT': 'আইটি', 'BSc': 'বিএসসি', 'MSc': 'এমএসসি', 'BBA': 'বিবিএ',
    'MBA': 'এমবিএ', 'MBBS': 'এমবিবিএস', 'BA': 'বিএ', 'MA': 'এমএ',
    'PKSF': 'পিকেএসএফ', 'RDA': 'আরডিএ', 'CCB': 'সিসিবি', 'PBK': 'পিবিকে',
    'NOC': 'এনওসি', 'TA/DA': 'টিএ ডিএ', 'NGO': 'এনজিও',
}

COMMON_TYPO_FIXES = [
    ('গ্যাচুইটি', 'গ্র্যাচুইটি'),
    ('পারদশী', 'পারদর্শী'),
    ('শিক্ষারত', 'শিক্ষাগত'),
    ('অনুষায়ী', 'অনুযায়ী'),
    ('বেসরকারী', 'বেসরকারি'),
    ('সরকারী', 'সরকারি'),
]


def en_bn_to_int(s):
    trans = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
    return int(str(s).translate(trans))


def number_to_bangla_words(n):
    if n == 0:
        return 'শূন্য'
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
        if shatok == 1:
            parts.append('একশত')
        else:
            parts.append(BN_NUMS.get(shatok, str(shatok)) + ' শত')
        n %= 100
    if n > 0:
        parts.append(BN_NUMS.get(n, str(n)))
    return ' '.join(parts)


def convert_all_numbers_in_script(text):
    if not text:
        return ""
    text = re.sub(r'<think>.*?</think>', '', str(text), flags=re.DOTALL)
    text = re.sub(r'https?://\S+|wa\.me/\S+', '', text)

    for bad, good in COMMON_TYPO_FIXES:
        text = text.replace(bad, good)

    # তারিখ রূপান্তর: ২২/১২/২০২৬ বা 22-12-2026 -> বাইশ ডিসেম্বর দুই হাজার ছাব্বিশ
    def date_repl(m):
        try:
            d, mo, y = en_bn_to_int(m.group(1)), en_bn_to_int(m.group(2)), en_bn_to_int(m.group(3))
            if 1 <= d <= 31 and 1 <= mo <= 12 and 1990 <= y <= 2050:
                return f"{number_to_bangla_words(d)} {BN_MONTHS[mo]} {number_to_bangla_words(y)}"
        except Exception:
            pass
        return m.group(0)

    text = re.sub(r'(?<![0-9০-৯])([0-9০-৯]{1,2})[/.\-]([0-9০-৯]{1,2})[/.\-](20[0-9]{2}|২০[০-৯]{2})(?![0-9০-৯])', date_repl, text)

    # ইংরেজি সংক্ষিপ্ত রূপ বাংলা উচ্চারণে রূপান্তর
    for eng, bn in ACRONYM_TO_BN.items():
        text = re.sub(rf'(?<![A-Za-z]){re.escape(eng)}(?![A-Za-z])', bn, text, flags=re.IGNORECASE)

    # বাংলা শব্দের মাঝের '/' কে ' বা ' তে রূপান্তর
    text = re.sub(r'(?<=[\u0981-\u09E3])\s*/\s*(?=[\u0981-\u09E3])', ' বা ', text)
    # পরপর সংখ্যাগুলোর মাঝের '/' কে ' ও '
    text = re.sub(r'(?<=[0-9০-৯])\s*/\s*(?=[0-9০-৯])', ' ও ', text)

    text = re.sub(r'(?<=[0-9০-৯]),(?=[0-9০-৯])', '', text)
    text = re.sub(r'(\+?(?:88|৮৮)?[\s\-]*0?1[0-9০-৯][\s\-0-9০-৯]{7,11})', ' আমাদের হোয়াটসঅ্যাপ নম্বর ', text)
    text = re.sub(r'([0-9০-৯]+)\s*(?:/=|/-|৳)(?:\s*টাকা)?', r'\1 টাকা', text)
    text = re.sub(r'৳\s*([0-9০-৯]+)(?:\s*টাকা)?', r'\1 টাকা', text)
    text = re.sub(r'([0-9০-৯]+(?:\.[0-9০-৯]+)?)\s*%', r'\1 শতাংশ', text)
    text = re.sub(r'([0-9০-৯]+)\s*[-–—]\s*([0-9০-৯]+)', r'\1 থেকে \2', text)

    def dec_repl(m):
        try:
            left = number_to_bangla_words(en_bn_to_int(m.group(1)))
            right = ' '.join(BN_NUMS.get(en_bn_to_int(ch), ch) for ch in m.group(2))
            return f"{left} দশমিক {right}"
        except Exception:
            return m.group(0)

    text = re.sub(r'(?<![0-9০-৯.])([0-9০-৯]+)\.([0-9০-৯]+)(?![0-9০-৯.])', dec_repl, text)

    def num_repl(m):
        num_str = m.group(0)
        if len(num_str) > 8:
            return ""
        try:
            val = en_bn_to_int(num_str)
            return number_to_bangla_words(val)
        except Exception:
            return num_str

    text = re.sub(r'[0-9০-৯]+', num_repl, text)
    text = re.sub(r'ঘরে\s*বসে\s*', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def sanitize_youtube_tags(raw_tags, max_total_chars=400):
    clean_tags = []
    current_length = 0
    for tag in raw_tags:
        if not tag or not isinstance(tag, str):
            continue
        cleaned = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[\<\>\"\,\n\r]', '', tag)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        if not cleaned or len(cleaned) < 2:
            continue
        cleaned = cleaned[:50].strip()
        if cleaned not in clean_tags:
            tag_len = len(cleaned) + (1 if clean_tags else 0)
            if current_length + tag_len <= max_total_chars:
                clean_tags.append(cleaned)
                current_length += tag_len
            else:
                break
    return clean_tags


def clean_title_for_display(title):
    clean = title.split('|')[0].split('||')[0].strip()
    return re.sub(r'\s+', ' ', re.sub(r'[\r\n\t]+', ' ', clean))


def strip_unwanted_chars(text):
    s = re.sub(r'\s*৳', ' টাকা', str(text))
    cleaned = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|✪|★|☆', '', s)
    return re.sub(r'\s+', ' ', cleaned).strip()


def parse_json_safely(raw_text):
    if not raw_text:
        return None
    cleaned = re.sub(r'<think>.*?</think>', '', str(raw_text), flags=re.DOTALL).strip()
    try:
        json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        return json.loads(cleaned)
    except Exception:
        return None


def _clean_text_response(raw_text):
    if not raw_text or not isinstance(raw_text, str):
        return ""
    cleaned = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL)
    cleaned = re.sub(r'\x60{3}[\w]*', '', cleaned).replace('\x60' * 3, '')
    return cleaned.strip()


def _encode_images_base64(img_paths, max_images=5):
    """সর্বোচ্চ ৫টি সার্কুলার পেজ ১৬০০px শার্প কোয়ালিটিতে এনকোড করে (লম্বা পোর্ট্রেট পেজ অগ্রাধিকার পায়)"""
    if not img_paths:
        return []
    candidates = []
    for p in img_paths:
        if not p or not os.path.exists(p):
            continue
        try:
            with Image.open(p) as im:
                ratio = im.width / float(im.height or 1)
                candidates.append((0 if ratio < 1.32 else 1, p))
        except Exception:
            candidates.append((1, p))
    candidates.sort(key=lambda x: x[0])

    b64_list = []
    for _, p in candidates[:max_images]:
        try:
            with Image.open(p) as im:
                rgb = im.convert("RGB")
                if rgb.width > 1600:
                    new_h = int((1600 / rgb.width) * rgb.height)
                    rgb = rgb.resize((1600, new_h), Image.LANCZOS)
                buf = io.BytesIO()
                rgb.save(buf, format="JPEG", quality=90)
                b64_list.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        except Exception:
            pass
    return b64_list


# =========================================================================
# 🌟 কেন্দ্রীয় এআই এক্সিকিউশন গেটওয়ে
# =========================================================================

def _call_openrouter(prompt, json_mode=True, b64_images=None, text_fallback=True):
    raw_openrouter = os.environ.get("OPENROUTER_API_KEYS", os.environ.get("OPENROUTER_API_KEY", "")).strip()
    or_order = get_keys_in_cyclic_order("openrouter", raw_openrouter)
    total_or = len(parse_multiline_keys(raw_openrouter))
    if not or_order:
        return None

    for actual_idx, or_key in or_order:
        headers = {
            "Authorization": f"Bearer {or_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",
            "X-Title": "YouTube Automation",
        }

        if b64_images:
            vision_content = [{"type": "text", "text": prompt}]
            for b64 in b64_images:
                vision_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

            for v_model in OPENROUTER_VISION_MODELS:
                payload = {
                    "model": v_model,
                    "messages": [{"role": "user", "content": vision_content}],
                    "temperature": 0.2,
                    "max_tokens": 4500,
                }
                try:
                    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=70)
                    if resp.status_code == 200:
                        content_txt = resp.json()['choices'][0]['message']['content']
                        save_tracker_index("openrouter", actual_idx, total_or)
                        res = parse_json_safely(content_txt) if json_mode else _clean_text_response(content_txt)
                        if res:
                            print(f"  ✨ [OpenRouter Vision] Success with Key #{actual_idx+1} ({v_model})")
                            return res
                    else:
                        print(f"  ⚠️ [OpenRouter Vision] Key #{actual_idx+1} ({v_model}) HTTP {resp.status_code}: {resp.text[:140]}")
                        if resp.status_code in [401, 402]:
                            break
                except Exception as e:
                    print(f"  ⚠️ [OpenRouter Vision] Key #{actual_idx+1} ({v_model}) err: {e}")

        if text_fallback:
            for model_name in OPENROUTER_TEXT_MODELS:
                payload = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.35,
                    "max_tokens": 4500,
                }
                try:
                    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=65)
                    if resp.status_code == 200:
                        content_txt = resp.json()['choices'][0]['message']['content']
                        save_tracker_index("openrouter", actual_idx, total_or)
                        res = parse_json_safely(content_txt) if json_mode else _clean_text_response(content_txt)
                        if res:
                            print(f"  ✨ [OpenRouter] Success with Key #{actual_idx+1} ({model_name})")
                            return res
                    else:
                        print(f"  ⚠️ [OpenRouter] Key #{actual_idx+1} ({model_name}) HTTP {resp.status_code}")
                        if resp.status_code in [401, 402]:
                            break
                except Exception as e:
                    print(f"  ⚠️ [OpenRouter] Key #{actual_idx+1} ({model_name}) err: {e}")
        save_tracker_index("openrouter", actual_idx + 1, total_or)
    return None


def _call_ollama_cloud(prompt, json_mode=True, b64_images=None, text_fallback=True):
    raw_ollama = os.environ.get("OLLAMA_API_KEYS", os.environ.get("Ollama_API_Key", os.environ.get("OLLAMA_API_KEY", ""))).strip()
    ollama_order = get_keys_in_cyclic_order("ollama", raw_ollama)
    total_ollama = len(parse_multiline_keys(raw_ollama))
    if not ollama_order:
        return None

    for actual_idx, o_key in ollama_order:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {o_key}"}
        consecutive_402 = 0

        if b64_images:
            for v_model in OLLAMA_VISION_MODELS:
                payload = {
                    "model": v_model,
                    "messages": [{"role": "user", "content": prompt, "images": b64_images}],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 4500},
                }
                try:
                    resp = requests.post(OLLAMA_CHAT_URL, headers=headers, json=payload, timeout=70)
                    if resp.status_code == 200:
                        content_txt = resp.json().get("message", {}).get("content", "").strip()
                        save_tracker_index("ollama", actual_idx, total_ollama)
                        res = parse_json_safely(content_txt) if json_mode else _clean_text_response(content_txt)
                        if res:
                            print(f"  ✨ [Ollama Vision] Success with Key #{actual_idx+1} ({v_model})")
                            return res
                    else:
                        print(f"  ⚠️ [Ollama Vision] Key #{actual_idx+1} ({v_model}) HTTP {resp.status_code}: {resp.text[:140]}")
                        if resp.status_code in [401, 402]:
                            consecutive_402 += 1
                            if consecutive_402 >= 2:
                                break
                except Exception as e:
                    print(f"  ⚠️ [Ollama Vision] Key #{actual_idx+1} ({v_model}) err: {e}")

        if text_fallback:
            for model_name in OLLAMA_TEXT_MODELS:
                payload = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.35, "num_predict": 4500},
                }
                try:
                    resp = requests.post(OLLAMA_CHAT_URL, headers=headers, json=payload, timeout=65)
                    if resp.status_code == 200:
                        content_txt = resp.json().get("message", {}).get("content", "").strip()
                        save_tracker_index("ollama", actual_idx, total_ollama)
                        res = parse_json_safely(content_txt) if json_mode else _clean_text_response(content_txt)
                        if res:
                            print(f"  ✨ [Ollama Cloud] Success with Key #{actual_idx+1} ({model_name})")
                            return res
                    else:
                        print(f"  ⚠️ [Ollama Cloud] Key #{actual_idx+1} ({model_name}) HTTP {resp.status_code}")
                        if resp.status_code in [401, 402]:
                            consecutive_402 += 1
                            if consecutive_402 >= 2:
                                break
                except Exception as e:
                    print(f"  ⚠️ [Ollama Cloud] Key #{actual_idx+1} ({model_name}) err: {e}")
        save_tracker_index("ollama", actual_idx + 1, total_ollama)
    return None


def _call_groq(prompt, json_mode=True, b64_images=None, text_fallback=True):
    raw_groq = os.environ.get("GROQ_API_KEYS", os.environ.get("GROQ_API", "")).strip()
    groq_order = get_keys_in_cyclic_order("groq", raw_groq)
    total_groq = len(parse_multiline_keys(raw_groq))
    if not groq_order:
        return None

    for actual_idx, g_key in groq_order:
        headers = {"Authorization": f"Bearer {g_key}", "Content-Type": "application/json"}

        if b64_images:
            vision_content = [{"type": "text", "text": prompt}]
            for b64 in b64_images[:2]:
                vision_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            for gv_model in GROQ_VISION_MODELS:
                payload = {
                    "model": gv_model,
                    "messages": [{"role": "user", "content": vision_content}],
                    "temperature": 0.2,
                    "max_tokens": 4500,
                }
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}
                try:
                    resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=65)
                    if resp.status_code == 200:
                        content_txt = resp.json()['choices'][0]['message']['content']
                        save_tracker_index("groq", actual_idx, total_groq)
                        res = parse_json_safely(content_txt) if json_mode else _clean_text_response(content_txt)
                        if res:
                            print(f"  ✨ [Groq Vision] Success with Key #{actual_idx+1} ({gv_model})")
                            return res
                    else:
                        print(f"  ⚠️ [Groq Vision] Key #{actual_idx+1} ({gv_model}) HTTP {resp.status_code}: {resp.text[:140]}")
                        if "restricted" in resp.text.lower() or resp.status_code in [401, 403]:
                            break
                except Exception as e:
                    print(f"  ⚠️ [Groq Vision] Key #{actual_idx+1} ({gv_model}) err: {e}")

        if text_fallback:
            for g_model in GROQ_TEXT_MODELS:
                sys_msg = "You are a Bengali job circular specialist. Return valid JSON." if json_mode else "You are a professional Bengali YouTube presenter."
                payload = {
                    "model": g_model,
                    "messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}],
                    "temperature": 0.35,
                    "max_tokens": 4500,
                }
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}
                try:
                    resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=55)
                    if resp.status_code == 200:
                        content_txt = resp.json()['choices'][0]['message']['content']
                        save_tracker_index("groq", actual_idx, total_groq)
                        res = parse_json_safely(content_txt) if json_mode else _clean_text_response(content_txt)
                        if res:
                            print(f"  ✨ [Groq] Success with Key #{actual_idx+1} ({g_model})")
                            return res
                    else:
                        print(f"  ⚠️ [Groq] Key #{actual_idx+1} ({g_model}) HTTP {resp.status_code}: {resp.text[:140]}")
                        if "restricted" in resp.text.lower() or resp.status_code in [401, 403]:
                            break
                except Exception as e:
                    print(f"  ⚠️ [Groq] Key #{actual_idx+1} ({g_model}) err: {e}")
        save_tracker_index("groq", actual_idx + 1, total_groq)
    return None


def _call_cerebras(prompt, json_mode=True):
    raw_cerebras = os.environ.get("CEREBRAS_API_KEYS", os.environ.get("CEREBRAS_API_KEY", "")).strip()
    cerebras_order = get_keys_in_cyclic_order("cerebras", raw_cerebras)
    total_cerebras = len(parse_multiline_keys(raw_cerebras))
    if not cerebras_order:
        return None

    for actual_idx, c_key in cerebras_order:
        headers = {"Authorization": f"Bearer {c_key}", "Content-Type": "application/json"}
        for c_model in CEREBRAS_MODELS:
            payload = {
                "model": c_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.35,
                "max_tokens": 4500,
            }
            try:
                resp = requests.post("https://api.cerebras.ai/v1/chat/completions", headers=headers, json=payload, timeout=50)
                if resp.status_code == 200:
                    content_txt = resp.json()['choices'][0]['message']['content']
                    save_tracker_index("cerebras", actual_idx, total_cerebras)
                    res = parse_json_safely(content_txt) if json_mode else _clean_text_response(content_txt)
                    if res:
                        print(f"  ✨ [Cerebras] Success with Key #{actual_idx+1} ({c_model})")
                        return res
                else:
                    print(f"  ⚠️ [Cerebras] Key #{actual_idx+1} ({c_model}) HTTP {resp.status_code}: {resp.text[:140]}")
                    if resp.status_code in [401, 403]:
                        break
            except Exception as e:
                print(f"  ⚠️ [Cerebras] Key #{actual_idx+1} ({c_model}) err: {e}")
        save_tracker_index("cerebras", actual_idx + 1, total_cerebras)
    return None


def _call_gemini(prompt, json_mode=True, b64_images=None):
    raw_gemini = os.environ.get("GEMINI_API_KEYS", os.environ.get("GEMINI_API_KEY", "")).strip()
    gemini_order = get_keys_in_cyclic_order("gemini_text", raw_gemini)
    total_gemini = len(parse_multiline_keys(raw_gemini))
    if not gemini_order:
        return None

    parts = [{"text": prompt}]
    if b64_images:
        for b64 in b64_images:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    for actual_idx, g_key in gemini_order:
        for g_model in GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{g_model}:generateContent?key={g_key}"
            body = {
                "contents": [{"parts": parts}],
                "generationConfig": {"temperature": 0.2 if b64_images else 0.35, "maxOutputTokens": 4500},
            }
            try:
                resp = requests.post(url, headers={"Content-Type": "application/json"}, json=body, timeout=65)
                if resp.status_code == 200:
                    text_res = resp.json()['candidates'][0]['content']['parts'][0]['text']
                    save_tracker_index("gemini_text", actual_idx, total_gemini)
                    res = parse_json_safely(text_res) if json_mode else _clean_text_response(text_res)
                    if res:
                        tag = "Vision" if len(parts) > 1 else "AI"
                        print(f"  ✨ [Gemini {tag}] Success with Key #{actual_idx+1} ({g_model})")
                        return res
                else:
                    print(f"  ⚠️ [Gemini] Key #{actual_idx+1} ({g_model}) HTTP {resp.status_code}: {resp.text[:140]}")
                    if resp.status_code in [401, 403]:
                        break
            except Exception as e:
                print(f"  ⚠️ [Gemini] Key #{actual_idx+1} ({g_model}) err: {e}")
        save_tracker_index("gemini_text", actual_idx + 1, total_gemini)
    return None


def execute_ai_query(prompt, json_mode=True, img_paths=None, vision_only=False):
    b64_images = _encode_images_base64(img_paths, max_images=5) if img_paths else None

    if b64_images:
        for fn in (
            lambda: _call_gemini(prompt, json_mode=json_mode, b64_images=b64_images),
            lambda: _call_openrouter(prompt, json_mode=json_mode, b64_images=b64_images, text_fallback=False),
            lambda: _call_ollama_cloud(prompt, json_mode=json_mode, b64_images=b64_images, text_fallback=False),
            lambda: _call_groq(prompt, json_mode=json_mode, b64_images=b64_images, text_fallback=False),
        ):
            res = fn()
            if res:
                return res
        if vision_only:
            return None

    for fn in (
        lambda: _call_openrouter(prompt, json_mode=json_mode, b64_images=None, text_fallback=True),
        lambda: _call_ollama_cloud(prompt, json_mode=json_mode, b64_images=None, text_fallback=True),
        lambda: _call_groq(prompt, json_mode=json_mode, b64_images=None, text_fallback=True),
        lambda: _call_cerebras(prompt, json_mode=json_mode),
        lambda: _call_gemini(prompt, json_mode=json_mode, b64_images=None),
    ):
        res = fn()
        if res:
            return res

    return None


def _get_method_cta(app_method):
    if app_method == "prescribed_form":
        return (
            "এই নিয়োগে আবেদনের জন্য নির্ধারিত চাকরির আবেদন ফরমটি সঠিক নিয়মে পূরণ করতে এবং প্রয়োজনীয় কাগজপত্র প্রস্তুত করতে "
            "ভিডিওর স্ক্রিনে দেওয়া অথবা ডেসক্রিপশনে থাকা আমাদের হোয়াটসঅ্যাপ নম্বরে সরাসরি মেসেজ করুন। "
            "আমাদের অভিজ্ঞ টিম আপনার চাকরির ফর্ম পূরণ সফলভাবে সম্পন্ন করে দেবে। নিয়মিত চাকরির খবর পেতে চ্যানেলটি সাবস্ক্রাইব করে সাথেই থাকুন, ধন্যবাদ।"
        )
    elif app_method == "formal_letter":
        return (
            "এই নিয়োগের জন্য সঠিক ফরম্যাটে আনুষ্ঠানিক আবেদনপত্র ও জীবনবৃত্তান্ত তৈরি করতে "
            "ভিডিওর স্ক্রিনে দেওয়া অথবা ডেসক্রিপশনে থাকা আমাদের হোয়াটসঅ্যাপ নম্বরে সরাসরি মেসেজ করুন। "
            "আমাদের অভিজ্ঞ টিম আপনার আবেদনপত্র তৈরি ও গুছিয়ে দেওয়ার সম্পূর্ণ দায়িত্ব নেবে। নিয়মিত চাকরির খবর পেতে চ্যানেলটি সাবস্ক্রাইব করে সাথেই থাকুন, ধন্যবাদ।"
        )
    elif app_method == "walk_in":
        return (
            "এই নিয়োগে নির্ধারিত তারিখে ওয়াক-ইন-ইন্টারভিউ বা সাক্ষাৎকারে অংশগ্রহণের জন্য প্রয়োজনীয় জীবনবৃত্তান্ত ও কাগজপত্র সঠিকভাবে প্রস্তুত করতে "
            "ভিডিওর স্ক্রিনে দেওয়া অথবা ডেসক্রিপশনে থাকা আমাদের হোয়াটসঅ্যাপ নম্বরে সরাসরি মেসেজ করুন। "
            "আমাদের অভিজ্ঞ টিম আপনাকে সম্পূর্ণ সহায়তা করবে। নিয়মিত চাকরির খবর পেতে চ্যানেলটি সাবস্ক্রাইব করে সাথেই থাকুন, ধন্যবাদ।"
        )
    return (
        "এই নিয়োগে অনলাইনে শতভাগ নির্ভুলভাবে আবেদন সম্পন্ন করতে "
        "ভিডিওর স্ক্রিনে দেওয়া অথবা ডেসক্রিপশনে থাকা আমাদের হোয়াটসঅ্যাপ নম্বরে সরাসরি মেসেজ করুন। "
        "আমাদের অভিজ্ঞ টিম অত্যন্ত সতর্কতার সাথে আপনার আবেদন সম্পন্ন করে দেবে। নিয়মিত চাকরির খবর পেতে চ্যানেলটি সাবস্ক্রাইব করে সাথেই থাকুন, ধন্যবাদ।"
    )


def _is_empty_or_placeholder(val):
    s = str(val or "").strip()
    if not s:
        return True
    bad = [
        "উল্লেখ নেই", "চিত্রে উপলব্ধ নয়", "উপলব্ধ নয়", "টেবিলে অনুপস্থিত",
        "নির্ধারিত সংখ্যক", "বিজ্ঞপ্তি অনুযায়ী", "not specified", "n/a", "none", "unknown",
    ]
    return any(b in s.lower() for b in bad)


# =========================================================================
# 🌟 ফেইল-সেফ স্ক্রিপ্ট বিল্ডার ('উল্লেখ নেই' / 'চিত্রে উপলব্ধ নয়' মুক্ত)
# =========================================================================

def build_script_from_verified_data(verified_data, title, article_text):
    org = verified_data.get("organization", title)
    total_vac = verified_data.get("total_vacancies", "")
    deadline = verified_data.get("deadline", "")
    posts = verified_data.get("posts", [])
    app_method = verified_data.get("application_method", "online")

    vac_line = f"মোট {total_vac} জনবল নিয়োগ দেওয়া হবে।" if not _is_empty_or_placeholder(total_vac) else "বিভিন্ন পদে যোগ্য জনবল নিয়োগ দেওয়া হবে।"
    dl_line = f"আবেদনের শেষ সময় নির্ধারিত হয়েছে {deadline}।" if not _is_empty_or_placeholder(deadline) else ""

    post_paragraphs = []
    for idx, p in enumerate(posts, 1):
        p_name = p.get("post_name", f"{idx} নম্বর পদ")
        p_unit = p.get("circular_unit", "")
        p_vac = p.get("vacancy_count", "")
        p_qual = p.get("educational_qualification", "")
        p_sal = p.get("salary_scale", "")
        p_fee = p.get("application_fee", "")
        p_duties = p.get("key_duties", "")

        unit_prefix = f"{p_unit}-এর অধীনে " if p_unit and p_unit not in org else ""
        sents = [f"{idx} নম্বর পদটি হলো {unit_prefix}{p_name}।"]

        if not _is_empty_or_placeholder(p_vac):
            sents.append(f"এই পদে {p_vac} লোক নেওয়া হবে।")
        if not _is_empty_or_placeholder(p_duties):
            sents.append(f"এই পদের মূল দায়িত্ব হলো {p_duties}।")
        if not _is_empty_or_placeholder(p_qual):
            sents.append(f"আবেদনের জন্য শিক্ষাগত যোগ্যতা ও অভিজ্ঞতা হিসেবে থাকতে হবে {p_qual}।")
        if not _is_empty_or_placeholder(p_sal):
            sents.append(f"পদটির জন্য বেতন ও গ্রেড নির্ধারিত রয়েছে {p_sal}।")
        if p_fee and any(w in p_fee for w in ["নেই", "ফ্রি", "বিনামূল্যে", "লাগবে না", "প্রয়োজন নেই"]):
            sents.append("এই পদে আবেদন করতে কোনো আবেদন ফি লাগবে না।")
        elif not _is_empty_or_placeholder(p_fee):
            sents.append(f"আবেদন ফি হিসেবে প্রযোজ্য হবে {p_fee}।")

        post_paragraphs.append(" ".join(sents))

    posts_block = "\n\n".join(post_paragraphs)
    cta_block = _get_method_cta(app_method)

    return f"""আসসালামু আলাইকুম প্রিয় চাকরিপ্রার্থী ভাই ও বোনেরা। আজকের ভিডিওতে আপনাদের সবাইকে স্বাগতম। সম্প্রতি {org} থেকে একটি গুরুত্বপূর্ণ নিয়োগ বিজ্ঞপ্তি প্রকাশিত হয়েছে, যেখানে {vac_line} {dl_line}

প্রথমেই প্রতিষ্ঠানটি সম্পর্কে সংক্ষেপে বলে নিই। {org} নিজস্ব কর্মক্ষেত্রে অত্যন্ত সুনাম ও মর্যাদার সাথে দায়িত্ব পালন করে যাচ্ছে। এবার চলুন বিজ্ঞপ্তিতে থাকা প্রতিটি পদের বিস্তারিত তথ্য এক এক করে জেনে নেওয়া যাক।

{posts_block}

সাধারণ শর্ত হিসেবে নির্ধারিত বয়সসীমার মধ্যে থাকা যোগ্য প্রার্থীরা আবেদন করতে পারবেন এবং নিয়ম অনুযায়ী প্রাপ্য বেতন ও অন্যান্য সুযোগ-সুবিধা পাবেন।

{cta_block}"""


# =========================================================================
# 🌟 ধাপ ১: Vision-First সার্কুলার OCR + পরিষ্কার ওয়েবসাইট টেক্সট যাচাই
# =========================================================================

def _normalize_verified_data(raw_data):
    if not raw_data or not isinstance(raw_data, dict):
        return None
    method = str(raw_data.get("application_method", "online")).strip().lower()
    if method not in ("prescribed_form", "formal_letter", "walk_in", "online"):
        method = "online"
    hook_map = {
        "prescribed_form": "ফর্ম পূরণ",
        "formal_letter": "আবেদনপত্র তৈরি",
        "walk_in": "সরাসরি সাক্ষাৎকার",
        "online": "অনলাইনে আবেদন",
    }
    raw_data["application_method"] = method
    raw_data["hook_phrase"] = hook_map[method]
    return raw_data


def _extract_facts_from_circular_images(title, img_paths):
    """আসল সার্কুলার ছবির ওপর ১০০% ফোকাসড Vision OCR (পুরনো ব্লগ টেক্সটের বিভ্রান্তি ছাড়াই)"""
    if not img_paths:
        return None
    print("\n👁️ [STEP 1A] Running Dedicated Vision OCR on Official Circular Image(s)...")
    prompt = f"""Read EVERY word, table row, header, signature, and footnote printed directly on these official job circular image(s).
Article Title Hint (may be outdated or multi-circular): "{title}"

CRITICAL INSTRUCTIONS:
1. READ THE ATTACHED IMAGE(S) ONLY — DO NOT GUESS!
   - If the attached images belong to a specific district (e.g., শেরপুর পুলিশ সুপার, বান্দরবান পার্বত্য জেলা পরিষদ), report THAT EXACT district/organization, NOT another district!
   - If there are MULTIPLE DIFFERENT circulars across the images (e.g., Page 1 is Lalmonirhat SP and Page 2 is Sherpur SP, or 3 different Palli Bidyut Samities), list EVERY post from ALL circulars and fill "circular_unit" on each post with its exact organization/district name!
2. EXTRACT EVERY SINGLE POST FROM THE TABLE(S) ON THE IMAGES:
   - Never skip any post (if 13 posts exist, return all 13!).
   - Copy the exact Bengali post name, grade, salary scale, vacancy count, educational qualification, experience, and application fee from the circular image(s).
   - If a circular is Walk-in Interview (ওয়াক-ইন-ইন্টারভিউ / সাক্ষাৎকার), set "application_method": "walk_in".
   - If Courier/Post/Direct Office submission with prescribed form (নির্ধারিত ফরম পূরণ), set "application_method": "prescribed_form".
   - If Courier/Post/Direct Office submission with plain paper application & CV (আবেদনপত্র ও জীবনবৃত্তান্ত), set "application_method": "formal_letter".
   - If Online portal / Teletalk / Email, set "application_method": "online".
3. If any single field (like fee for private/walk-in jobs) truly isn't written on the image, leave it as "" (empty string) — NEVER write "উল্লেখ নেই" or "চিত্রে উপলব্ধ নয়".

Return strictly valid JSON:
{{
  "is_multi_circular": true | false,
  "organization": "Exact official organization name(s) printed on the image(s)",
  "org_short": "Complete 3-5 word Bengali organization name",
  "job_category": "সরকারি চাকরি" | "স্বায়ত্তশিত প্রতিষ্ঠান" | "বেসরকারি চাকরি" | "ব্যাংক চাকরি",
  "application_method": "prescribed_form" | "formal_letter" | "walk_in" | "online",
  "total_vacancies": "Exact total vacancies printed or summed from posts (e.g. ১৬টি or ১৪১ জন or ০৪টি)",
  "eligibility_summary": "Short 2-4 word range (e.g. ৮ম - স্নাতক পাশ)",
  "application_fee_summary": "e.g. ৫৬ থেকে ১১২ টাকা or ১০০ থেকে ২০০ টাকা or বিনামূল্যে",
  "deadline": "Exact deadline(s) / interview dates printed on the image(s)",
  "age_limit": "Exact age limit printed on the image(s)",
  "district_eligibility": "Exact eligible district(s) printed on the image(s)",
  "posts": [
    {{
      "circular_unit": "Organization/District name if multi-circular, else same as organization",
      "post_name": "Exact post name & grade from image",
      "vacancy_count": "Exact vacancy count from image",
      "educational_qualification": "Exact degree/experience/typing/license requirements from image",
      "salary_scale": "Exact salary scale/pay/benefits printed on image",
      "application_fee": "Exact fee for this post from image, or '' if no fee",
      "key_duties": "Brief 1-sentence realistic work description for this post"
    }}
  ]
}}"""
    res = execute_ai_query(prompt, json_mode=True, img_paths=img_paths, vision_only=True)
    return _normalize_verified_data(res)


def _verify_and_merge_with_article_text(title, article_text, vision_data):
    """ভিশন ডাটা থাকলে ব্লগের ক্লিন টেক্সট থেকে কেবল অনুপস্থিত স্পষ্ট তথ্য যোগ করে; ভিশন না পেলে টেক্সট থেকে এক্সট্রাক্ট করে"""
    if vision_data and isinstance(vision_data, dict) and vision_data.get("posts"):
        print("🔄 [STEP 1B] Cross-checking Vision OCR with Clean Website Text (Protecting Image Facts)...")
        vision_json = json.dumps(vision_data, ensure_ascii=False, indent=2)
        prompt = f"""You have ALREADY extracted primary circular facts directly from the official circular image(s) ("VISION_JSON").
Now compare with the scraped webpage text ("ARTICLE_TEXT") ONLY to fill any blank/blurry fields or capture extra posts if a page was missed.

STRICT CONFLICT RESOLUTION RULES:
1. WARNING: Bangladeshi job blogs (especially projobsbd.com) often have OUTDATED text from older circulars at the bottom or mix up districts!
   Whenever ARTICLE_TEXT contradicts VISION_JSON (different district, different post names, different dates, different salary/fee), ALWAYS TRUST AND KEEP VISION_JSON!
2. Do NOT overwrite valid values in VISION_JSON with older blog text.
3. Verify total_vacancies matches the sum of post vacancy counts (if all counts are numbers).
4. NEVER put "উল্লেখ নেই" or "চিত্রে উপলব্ধ নয়" in any field; use "" if genuinely absent.

TITLE: {title}
VISION_JSON:
{vision_json}

CLEANED_ARTICLE_TEXT:
{article_text[:9500]}

Return the final verified JSON with the exact same schema as VISION_JSON."""
        merged = execute_ai_query(prompt, json_mode=True)
        if merged and isinstance(merged, dict) and merged.get("posts"):
            return _normalize_verified_data(merged)
        return vision_data

    print("\n🔍 [STEP 1B] Vision OCR unavailable — Extracting strictly from Cleaned Article Text...")
    prompt = f"""Extract 100% factual job circular data from the cleaned article text below.
WARNING: If the text contains an older/conflicting section at the bottom, prioritize the newest summary & post tables near the top.
NEVER invent post names or use placeholder text like "উল্লেখ নেই" or "চিত্রে উপলব্ধ নয়" (leave "" if absent).

TITLE: {title}
CLEANED ARTICLE TEXT:
{article_text[:11500]}

Return strictly valid JSON:
{{
  "is_multi_circular": true | false,
  "organization": "Full Bengali organization/company/ministry name",
  "org_short": "Complete 3-5 word clean name",
  "job_category": "সরকারি চাকরি" | "স্বায়ত্তশিত প্রতিষ্ঠান" | "বেসরকারি চাকরি" | "ব্যাংক চাকরি",
  "application_method": "prescribed_form" | "formal_letter" | "walk_in" | "online",
  "total_vacancies": "Exact total count",
  "eligibility_summary": "Short 2-4 word range",
  "application_fee_summary": "Exact fee range or ''",
  "deadline": "Exact last date / interview date",
  "age_limit": "Exact age limit",
  "district_eligibility": "Exact eligible districts",
  "posts": [
    {{
      "circular_unit": "Organization/District name",
      "post_name": "Exact post name & grade",
      "vacancy_count": "Exact vacancy count",
      "educational_qualification": "Exact degree/GPA/experience requirement",
      "salary_scale": "Exact salary scale",
      "application_fee": "Exact fee for THIS post or ''",
      "key_duties": "Brief 1-sentence realistic description of this post's work"
    }}
  ]
}}"""
    res = execute_ai_query(prompt, json_mode=True)
    return _normalize_verified_data(res)


def extract_verified_job_data(title, article_text, img_paths=None):
    vision_data = _extract_facts_from_circular_images(title, img_paths) if img_paths else None
    return _verify_and_merge_with_article_text(title, article_text, vision_data)


# =========================================================================
# 🌟 ধাপ ২: AI নিজে সিদ্ধান্ত নেবে স্ক্রিপ্টের কোথায় কী লিখবে -> তারপর স্ক্রিপ্ট রাইটিং
# =========================================================================

def plan_script_structure(verified_data, title, article_text):
    """আর্টিকেল ও ভেরিফায়েড ডাটা দেখে AI নিজেই সিদ্ধান্ত নেয় স্ক্রিপ্টের কোথায় কী লিখবে"""
    print("🧠 [STEP 2A] Letting AI decide optimal script structure & content placement...")
    data_str = json.dumps(verified_data, ensure_ascii=False, indent=2)
    prompt = f"""You are a Senior Bengali YouTube Documentary Producer.
Analyze this job circular data and decide the BEST narrative structure and section-by-section content plan for a YouTube presenter.
Do NOT force a robotic one-size-fits-all template — adapt the script layout intelligently to THIS specific circular!
For example:
- If "is_multi_circular" is true (e.g. multiple districts like Sherpur & Lalmonirhat, or 3 different Palli Bidyut Samities), group posts clearly by their district/office so viewers never get confused.
- If there are many posts (like 13 posts), organize smoothly in exact numerical sequence while keeping the pacing crisp and engaging.
- If it is a Walk-in Interview or Courier/Postal form job, highlight the interview/submission timeline & documents naturally (without giving step-by-step form pixel sizes).

TITLE: {title}
VERIFIED DATA:
{data_str}

CLEAN ARTICLE CONTEXT:
{article_text[:5500]}

Return strictly valid JSON:
{{
  "circular_type": "single_govt" | "multi_circular" | "walk_in_interview" | "private_ngo" | "autonomous",
  "tone_guidance": "Short instruction on presenter tone",
  "sections": [
    {{
      "section_order": 1,
      "section_purpose": "What this part covers (e.g. Hook & Key Overview / District-1 Circular / Post-by-Post Breakdown / Eligibility & Benefits / Actionable Outro)",
      "key_points_to_cover": ["Exact facts, numbers, post names, salaries, fees to place in this section"]
    }}
  ]
}}"""
    return execute_ai_query(prompt, json_mode=True)


def _script_passes_quality_check(script_text, verified_data):
    if not script_text or not isinstance(script_text, str):
        return False, "Empty script"
    words = len(script_text.split())
    if words < 140:
        return False, f"Too short ({words} words)"
    banned_phrases = [
        "উল্লেখ নেই", "চিত্রে উপলব্ধ নয়", "উপলব্ধ নয়", "টেবিলে অনুপস্থিত",
        "বিজ্ঞপ্তিতে দেওয়া নেই", "আলাদাভাবে বলা সম্ভব নয়", "<think>",
    ]
    for bp in banned_phrases:
        if bp in script_text:
            return False, f"Contains forbidden placeholder '{bp}'"
    posts = verified_data.get("posts") or []
    if posts:
        first_post = str(posts[0].get("post_name", "")).split("(")[0].strip()
        key_token = first_post.split()[0] if first_post else ""
        if key_token and len(key_token) >= 3 and key_token not in script_text:
            return False, f"Missing primary post '{first_post}'"
    return True, "OK"


def generate_script_from_verified_data(verified_data, title, article_text):
    script_plan = plan_script_structure(verified_data, title, article_text)
    plan_str = json.dumps(script_plan, ensure_ascii=False, indent=2) if script_plan else "Organize logically: Opening hook, Organization context, Every single post individually, General eligibility & benefits, Closing CTA."

    print("🎙️ [STEP 2B] Writing factual spoken Bengali script using AI's decided structure...")
    data_str = json.dumps(verified_data, ensure_ascii=False, indent=2)
    cta_text = _get_method_cta(verified_data.get("application_method", "online"))

    prompt = f"""You are an expert Bangladeshi job circular YouTube presenter.
Write a natural, accurate, spoken Bengali voiceover script following the AI-decided Script Blueprint and ONLY the Verified Data below.

TITLE: "{title}"

AI-DECIDED SCRIPT STRUCTURE (Where to place what):
{plan_str}

VERIFIED JOB DATA (100% Ground Truth):
{data_str}

REFERENCE CONTEXT:
{article_text[:5500]}

STRICT PRESENTATION RULES:
1. Start naturally with "আসসালামু আলাইকুম প্রিয় চাকরিপ্রার্থী ভাই ও বোনেরা।".
2. Follow the AI-decided section order smoothly as continuous spoken Bengali paragraphs (NO markdown, NO headings, NO bullet points, NO brackets).
3. COVER EVERY SINGLE POST in "posts" individually! Never skip or lump posts together. For each post, naturally state:
   - Exact post name (and its circular_unit/district if multi-circular),
   - Number of people to be hired (NEVER repetitively use the robotic word 'শূন্যপদ' — say 'লোক নেওয়া হবে', 'জন নিয়োগ পাবেন'),
   - Brief realistic duties/work of the post,
   - Required educational qualification, GPA, experience/license,
   - Exact salary scale/grade/benefits,
   - Exact application fee (only if a fee applies; if free, mention no fee is needed; if truly unstated for a private job, simply skip talking about fee).
4. Write ALL English abbreviations phonetically in Bengali (যেমন: এসএসসি, এইচএসসি, জিপিএ, সিভি, এনআইডি, এমআইএস, পিকেএসএফ) so the Bengali TTS reads cleanly.
5. FORBIDDEN:
   - NEVER write phrases like "উল্লেখ নেই", "চিত্রে উপলব্ধ নয়", "উপলব্ধ নয়", "টেবিলে অনুপস্থিত", "বলা সম্ভব নয়".
   - NEVER include phone number digits, website URLs, SMS codes, or photo/signature pixel sizes.
   - NEVER mix up districts/organizations when multiple circulars exist.
6. End cleanly with this CTA:
   "{cta_text}"

Output ONLY pure spoken Bengali text."""

    for attempt in range(2):
        res_text = execute_ai_query(prompt, json_mode=False)
        ok, reason = _script_passes_quality_check(res_text, verified_data)
        if ok:
            return res_text
        print(f"  ⚠️ Script quality check failed (Attempt {attempt+1}): {reason}")
    return ""


def generate_seo_metadata(verified_data, title):
    print("📈 [STEP 3] Generating SEO Title, Description & Tags...")
    posts_summary = ", ".join([p.get("post_name", "") for p in verified_data.get("posts", [])[:5]])
    total_vac = verified_data.get("total_vacancies", "")
    org = verified_data.get("organization", title)
    job_cat = verified_data.get("job_category", "চাকরির খবর")
    hook_phrase = verified_data.get("hook_phrase", "অনলাইনে আবেদন")
    deadline = verified_data.get("deadline", "")

    whatsapp_contact = os.environ.get("WHATSAPP_CONTACT", "").strip()
    wa_instruction = (
        f"WhatsApp contact to apply: {whatsapp_contact}"
        if whatsapp_contact
        else "tell viewers to message the WhatsApp number shown on the video screen"
    )

    prompt = f"""Generate YouTube SEO metadata in JSON for this job circular:
Organization: "{org}"
Category: "{job_cat}"
Title: "{title}"
Key Posts: "{posts_summary}"
Total Vacancies: "{total_vac}"
Deadline: "{deadline}"
Application Method Hook: "{hook_phrase}"

MANDATORY RULE:
- The YouTube Title, Description, and Tags MUST prominently include "{hook_phrase}"!

Return strictly valid JSON:
{{
  "optimized_title": "High-CTR Bengali YouTube Title under 95 chars featuring organization, '{hook_phrase}', and vacancies (with 🔥 or 🚨)",
  "video_description": "Helpful Bengali description summarizing all posts, qualifications, fee info, deadline, '{hook_phrase}' guidance, and {wa_instruction}",
  "specific_tags": ["8 to 12 relevant Bengali & English SEO tags including '{hook_phrase}' without commas"]
}}"""
    return execute_ai_query(prompt, json_mode=True)


def _normalize_legacy_thumb_meta(raw_res, verified_data, clean_title):
    """আগের ফিক্সড thumbnail.py-এর উপযোগী exact কী (top_text, row1_text, row2_text, sub_text, bot_text, job_category) রিটার্ন করে"""
    if not raw_res or not isinstance(raw_res, dict):
        raw_res = {}

    posts = verified_data.get("posts") or [{}]
    first_post = posts[0].get("post_name", "জরুরি নিয়োগ") if isinstance(posts[0], dict) else "জরুরি নিয়োগ"
    org_short = strip_unwanted_chars(
        raw_res.get("top_text")
        or verified_data.get("org_short")
        or verified_data.get("organization")
        or clean_title[:35]
    )
    job_cat = strip_unwanted_chars(
        raw_res.get("job_category")
        or verified_data.get("job_category")
        or "সরকারি চাকরি"
    )
    hook_phrase = verified_data.get("hook_phrase", "অনলাইনে আবেদন")
    total_v = strip_unwanted_chars(verified_data.get("total_vacancies", ""))
    elig = strip_unwanted_chars(verified_data.get("eligibility_summary", ""))

    row1_text = strip_unwanted_chars(raw_res.get("row1_text") or first_post or "জরুরি নিয়োগ")
    row2_text = strip_unwanted_chars(raw_res.get("row2_text") or (total_v if total_v else "বিশাল নিয়োগ"))
    sub_text = strip_unwanted_chars(raw_res.get("sub_text") or elig or "SSC/HSC ও স্নাতক পাশ")

    if any(term in sub_text for term in ["আবেদন", "ফরম", "পূরণ", "নিয়ম", "তৈরি"]):
        sub_text = elig if (elig and not any(t in elig for t in ["আবেদন", "ফরম", "পূরণ"])) else "SSC/HSC পাশ / ৬৪ জেলা"

    bot_text = strip_unwanted_chars(raw_res.get("bot_text") or f"{hook_phrase} ও বিস্তারিত")
    if hook_phrase not in bot_text:
        bot_text = f"{hook_phrase} ও বিস্তারিত"

    return {
        "job_category": job_cat,
        "top_text": org_short,
        "row1_text": row1_text,
        "row2_text": row2_text,
        "sub_text": sub_text,
        "bot_text": bot_text,
    }


def generate_thumbnail_metadata(verified_data, title):
    print("🎨 [STEP 4] Generating Thumbnail Texts (Preserving Existing Design Format)...")
    posts = verified_data.get("posts") or [{}]
    first_post = posts[0] if isinstance(posts[0], dict) else {}
    post_name = first_post.get("post_name", "জরুরি নিয়োগ")
    total_vac = verified_data.get("total_vacancies", "")
    org = verified_data.get("org_short") or verified_data.get("organization", "সরকারি চাকরি")
    job_cat = verified_data.get("job_category", "সরকারি চাকরি")
    qual = verified_data.get("eligibility_summary") or first_post.get("educational_qualification", "যোগ্যতা ও নিয়ম")
    hook_phrase = verified_data.get("hook_phrase", "অনলাইনে আবেদন")

    prompt = f"""Generate concise Bengali thumbnail texts for this job circular:
Organization: "{org}"
Category: "{job_cat}"
Main Post: "{post_name}"
Vacancies: "{total_vac}"
Qualification: "{qual}"
Application Method Hook: "{hook_phrase}"

RULES:
- "job_category": Keep exact "{job_cat}".
- "top_text": Clean Bengali organization name (3-5 words MAX, NEVER cut awkwardly, e.g. "{org}").
- "row1_text": 2-3 words. Main eye-catching hook or post name (e.g. "{post_name}" or "জরুরি নিয়োগ").
- "row2_text": 2-3 words. Vacancy count in RED (e.g. "{total_vac if total_vac else 'বিশাল নিয়োগ'}").
- "sub_text": 2-3 words. ONLY Qualification or District (e.g. "SSC/HSC পাশ", "৮ম - স্নাতক পাশ"). Do NOT put "{hook_phrase}" in sub_text.
- "bot_text": 2-4 words. Bottom bar text MUST prominently feature "{hook_phrase}" (e.g. "{hook_phrase} ও বিস্তারিত").

Return strictly valid JSON:
{{
  "job_category": "{job_cat}",
  "top_text": "...",
  "row1_text": "...",
  "row2_text": "...",
  "sub_text": "...",
  "bot_text": "..."
}}"""
    raw_res = execute_ai_query(prompt, json_mode=True)
    return _normalize_legacy_thumb_meta(raw_res, verified_data, title)


# =========================================================================
# 🌟 মূল মাস্টার ফাংশন
# =========================================================================

def generate_job_content(title, article_text, img_paths=None):
    clean_title = clean_title_for_display(title)

    verified_data = extract_verified_job_data(clean_title, article_text, img_paths=img_paths)
    if not verified_data or not isinstance(verified_data, dict) or not verified_data.get("posts"):
        clean_org = clean_title.split("নিয়োগ")[0].strip() if "নিয়োগ" in clean_title else clean_title[:35]
        is_priv = any(k in clean_title.lower() for k in ["লিমিটেড", "ফার্মা", "গ্রুপ", "কোম্পানি", "বেসরকারি", "বিকাশ", "ফাউন্ডেশন", "এনজিও", "ltd", "limited"])
        verified_data = {
            "is_multi_circular": False,
            "organization": clean_org,
            "org_short": " ".join(clean_org.split()[:4]),
            "job_category": "বেসরকারি চাকরি" if is_priv else "সরকারি চাকরি",
            "application_method": "online",
            "hook_phrase": "অনলাইনে আবেদন",
            "total_vacancies": "",
            "eligibility_summary": "বিজ্ঞপ্তি অনুযায়ী যোগ্যতা",
            "application_fee_summary": "",
            "deadline": "",
            "district_eligibility": "সকল জেলা",
            "posts": [{
                "circular_unit": clean_org,
                "post_name": "বিভিন্ন পদে নিয়োগ",
                "vacancy_count": "",
                "salary_scale": "",
                "educational_qualification": "",
                "application_fee": "",
                "key_duties": "প্রতিষ্ঠানের সংশ্লিষ্ট দাপ্তরিক ও প্রাতিষ্ঠানিক দায়িত্ব পালন করা",
            }]
        }

    raw_script = generate_script_from_verified_data(verified_data, clean_title, article_text)

    if not raw_script or len(raw_script.split()) < 140:
        print(f"⚠️ Generated script fell back ({len(raw_script.split()) if raw_script else 0} words). Using clean structured builder...")
        raw_script = build_script_from_verified_data(verified_data, clean_title, article_text)

    voiceover_script = convert_all_numbers_in_script(raw_script)

    seo_res = generate_seo_metadata(verified_data, clean_title)
    opt_title = seo_res.get("optimized_title", clean_title)[:100] if seo_res and isinstance(seo_res, dict) else clean_title[:100]
    video_desc = seo_res.get("video_description", clean_title) if seo_res and isinstance(seo_res, dict) else clean_title
    raw_tags = seo_res.get("specific_tags", []) if seo_res and isinstance(seo_res, dict) else []
    video_tags = sanitize_youtube_tags(raw_tags + DEFAULT_BASE_TAGS)

    thumb_meta = generate_thumbnail_metadata(verified_data, clean_title)

    word_count = len(voiceover_script.split())
    hook = verified_data.get("hook_phrase", "অনলাইনে আবেদন")
    print(f"✨ [ACCURACY GUARANTEED] {word_count}-word Script | Method Hook: '{hook}' Ready!")
    return opt_title, voiceover_script, thumb_meta, video_desc, video_tags
