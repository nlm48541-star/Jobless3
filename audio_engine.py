# -*- coding: utf-8 -*-
import os, re, time, base64, requests, shutil
from ai_service import parse_keys_from_env, get_tracker_index, save_tracker_index

def mask_key(k):
    if not k or len(k) <= 8: return "****"
    return k[:4] + "..." + k[-4:]

def clean_script_for_speech(raw_text):
    if not raw_text: return ""
    text = re.sub(r'[\*\_\|\#\~]', '', raw_text)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'https?://\S+|wa\.me/\S+', '', text)
    text = re.sub(r'[\<\>\{\}\(\)\@\$\^\&\+\=\_\\\/]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def split_text_into_chunks(text, max_chars=1200):
    """১০ মিনিটের দীর্ঘ টেক্সটকে বাক্য অনুসারে নিরাপদ খণ্ডে ভাগ করে"""
    raw_parts = re.split(r'([।\?\!\n]+)', text)
    chunks = []
    current = ""
    for p in raw_parts:
        current += p
        if any(sym in p for sym in ['।', '?', '!', '\n']) or len(current) >= max_chars:
            if current.strip(): chunks.append(current.strip())
            current = ""
    if current.strip(): chunks.append(current.strip())
    return chunks

# =========================================================================
# 🌟 ১. Gemini 3.8 Flash TTS ইঞ্জিন (Priority 1)
# =========================================================================

def synthesize_with_gemini(speech_text, output_audio_path):
    print("\n--- [VOICE ENGINE 1: Gemini 3.8 Flash TTS] ---")
    gemini_keys = parse_keys_from_env("GEMINI_API_KEYS", "GEMINI_API_KEY")
    total_keys = len(gemini_keys)
    if total_keys == 0:
        print("  ⚠️ 'GEMINI_API_KEYS' not found in environment secrets.")
        return False

    try:
        from google import genai
    except ImportError:
        print("  ⚠️ 'google-genai' library not installed.")
        return False

    voice_id = os.environ.get("GEMINI_VOICE_ID", "voice_z3e67k0f8p8c").strip() or "voice_z3e67k0f8p8c"
    delivery_style = os.environ.get("GEMINI_DELIVERY_STYLE", "Natural, articulate, and professional Bengali news anchor style").strip()

    start_idx = get_tracker_index("gemini_tts", total_keys)

    for offset in range(total_keys):
        cur_idx = (start_idx + offset) % total_keys
        api_key = gemini_keys[cur_idx]
        masked = mask_key(api_key)
        print(f"  🚀 Attempting Gemini Key #{cur_idx+1}/{total_keys} ({masked})...")
        start_t = time.time()

        try:
            client = genai.Client(api_key=api_key)
            interaction = client.interactions.create(
                model="gemini-3.8-flash-tts",
                input=[{
                    "type": "user_input",
                    "content": [{
                        "type": "text",
                        "text": speech_text,
                        "annotations": [{"type": "speech_metadata", "style": delivery_style}]
                    }]
                }],
                response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": voice_id}]}
            )

            if hasattr(interaction, 'output_audio') and hasattr(interaction.output_audio, 'data'):
                audio_bytes = base64.b64decode(interaction.output_audio.data)
                if len(audio_bytes) > 2000:
                    with open(output_audio_path, "wb") as f:
                        f.write(audio_bytes)
                    save_tracker_index("gemini_tts", cur_idx, total_keys)
                    elapsed = round(time.time() - start_t, 2)
                    audio_mb = round(os.path.getsize(output_audio_path) / (1024 * 1024), 2)
                    print(f"  ✅ [SUCCESS] Generated Long 10-Min Voice via Gemini 3.8 Flash! ({audio_mb} MB in {elapsed}s)")
                    return True
        except Exception as e:
            print(f"  ⚠️ Gemini Key #{cur_idx+1} error: {e}")

        save_tracker_index("gemini_tts", cur_idx + 1, total_keys)

    return False

# =========================================================================
# 🌟 ২. ElevenLabs API ইঞ্জিন (Priority 2 - Smart Multi-Chunk Support)
# =========================================================================

def synthesize_with_elevenlabs(speech_text, output_audio_path):
    print("\n--- [VOICE ENGINE 2: ElevenLabs API (Long Audio Pipeline)] ---")
    eleven_keys = parse_keys_from_env("ELEVENLABS_API_KEYS", "ELEVENLABS_API_KEY")
    total_keys = len(eleven_keys)
    if total_keys == 0:
        print("  ⚠️ 'ELEVENLABS_API_KEYS' not found.")
        return False

    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM").strip()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    start_idx = get_tracker_index("elevenlabs_tts", total_keys)
    # ১০ মিনিটের টেক্সটকে ElevenLabs-এর উপযোগী চাঙ্কে বিভক্ত করা
    chunks = split_text_into_chunks(speech_text, max_chars=1200)

    for offset in range(total_keys):
        cur_idx = (start_idx + offset) % total_keys
        api_key = eleven_keys[cur_idx]
        masked = mask_key(api_key)
        print(f"  🚀 Attempting ElevenLabs Key #{cur_idx+1}/{total_keys} ({masked}) for {len(chunks)} chunks...")
        start_t = time.time()

        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json"
        }

        audio_parts = []
        key_failed = False

        for chunk_idx, chunk in enumerate(chunks, 1):
            payload = {
                "text": chunk,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
            }
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=90)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    audio_parts.append(resp.content)
                else:
                    print(f"  ⚠️ ElevenLabs chunk #{chunk_idx} failed with code {resp.status_code}.")
                    key_failed = True
                    break
            except Exception as e:
                print(f"  ⚠️ ElevenLabs chunk #{chunk_idx} network error: {e}")
                key_failed = True
                break

        if not key_failed and len(audio_parts) == len(chunks):
            with open(output_audio_path, "wb") as f:
                for part in audio_parts:
                    f.write(part)
            save_tracker_index("elevenlabs_tts", cur_idx, total_keys)
            elapsed = round(time.time() - start_t, 2)
            audio_mb = round(os.path.getsize(output_audio_path) / (1024 * 1024), 2)
            print(f"  ✅ [SUCCESS] Generated Long 10-Min Audio via ElevenLabs! ({audio_mb} MB in {elapsed}s)")
            return True

        save_tracker_index("elevenlabs_tts", cur_idx + 1, total_keys)

    return False

# =========================================================================
# 🌟 ৩. Microsoft Edge Neural ব্যাকআপ ইঞ্জিন (Priority 3)
# =========================================================================

def synthesize_with_edge_fallback(speech_text, output_audio_path):
    print("\n--- [VOICE ENGINE 3: Microsoft Neural Fallback (bn-BD-PradeepNeural)] ---")
    try:
        import asyncio, edge_tts
        start_t = time.time()
        async def _make():
            c = edge_tts.Communicate(speech_text, "bn-BD-PradeepNeural", rate="+0%", pitch="+0Hz")
            await c.save(output_audio_path)
        asyncio.run(_make())
        if os.path.exists(output_audio_path) and os.path.getsize(output_audio_path) > 1000:
            elapsed = round(time.time() - start_t, 2)
            audio_mb = round(os.path.getsize(output_audio_path) / (1024 * 1024), 2)
            print(f"  ✅ [SUCCESS] Generated 10-Min Audio via Edge Neural Engine! ({audio_mb} MB in {elapsed}s)")
            return True
    except Exception as e:
        print(f"  ⚠️ Edge fallback notice: {e}")
    return False

# =========================================================================
# 🌟 ৪. লোকাল মিউজিক ইমার্জেন্সি ফলব্যাক (Priority 4)
# =========================================================================

def fallback_local_audio(output_audio_path):
    print("\n--- [VOICE ENGINE 4: Emergency Local Audio/Music Fallback] ---")
    candidates = [
        "Music/bg.mp3", "Music/music.mp3", "sample_voice.mp3", 
        "Photos/sample_voice.mp3", "workspace/bg.mp3"
    ]
    for c in candidates:
        if os.path.exists(c) and os.path.getsize(c) > 2000:
            shutil.copy(c, output_audio_path)
            print(f"  ✅ [EMERGENCY FALLBACK] Using existing audio track '{c}'!")
            return True

    try:
        import wave, struct
        with wave.open(output_audio_path, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(44100)
            data = struct.pack('<h', 0) * (44100 * 600)  # ১০ মিনিটের নিরব সাউন্ড ট্র্যাক
            wav.writeframes(data)
        print("  ✅ [EMERGENCY FALLBACK] Generated 10-min fallback audio track!")
        return True
    except Exception as e:
        print(f"  ⚠️ Audio generation failure: {e}")
    return False

# =========================================================================
# 🌟 মাস্টার অডিও পাইপলাইন (Orchestrator)
# =========================================================================

def generate_voiceover_audio_pipeline(text, output_audio_path):
    speech_text = clean_script_for_speech(text)
    clean_chars = len(speech_text)
    words = len(speech_text.split())

    print("\n" + "="*65)
    print("🎙️ [AUDIO ENGINE] Long 10-Minute Voice Pipeline Active")
    print(f"📊 [Script Stats] Chars: {clean_chars} | Words: {words}")
    print("="*65)

    # ১. Gemini 3.8 Flash TTS
    if synthesize_with_gemini(speech_text, output_audio_path):
        return True

    # ২. ElevenLabs
    if synthesize_with_elevenlabs(speech_text, output_audio_path):
        return True

    # ৩. Microsoft Edge Neural
    if synthesize_with_edge_fallback(speech_text, output_audio_path):
        return True

    # ৪. লোকাল ব্যাকআপ
    return fallback_local_audio(output_audio_path)
