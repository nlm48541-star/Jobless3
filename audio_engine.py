# -*- coding: utf-8 -*-
import io
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from ai_service import convert_all_numbers_in_script

_NINADA_ENGINE = None


def clean_script_for_speech(raw_text):
    if not raw_text:
        return ""
    text = convert_all_numbers_in_script(raw_text)
    text = re.sub(r'[\*\_\|\#\~\x60]', '', text)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'https?://\S+|wa\.me/\S+', '', text)
    text = re.sub(r'[\<\>\{\}\(\)\@\$\^\&\+\=\_\\\/]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _split_text_for_ninada(text, max_chars=450):
    """স্বাভাবিক দাঁড়ি-কমা বহাল রেখে দীর্ঘ স্ক্রিপ্টকে নিরাপদ বাক্য-খণ্ডে বিভক্ত করে"""
    text = re.sub(r'\s+', ' ', str(text)).strip()
    if not text:
        return []

    raw_sents = [s.strip() for s in re.split(r'(?<=[।\.\?\!\n])\s*', text) if s.strip()]
    pieces = []
    for s in raw_sents:
        if len(s) <= max_chars:
            pieces.append(s)
        else:
            sub_parts = [p.strip() for p in re.split(r'(?<=[,;—\-])\s*', s) if p.strip()]
            for sp in sub_parts:
                if len(sp) <= max_chars:
                    pieces.append(sp)
                else:
                    words = sp.split()
                    cur = ""
                    for w in words:
                        if len(cur) + len(w) + 1 <= max_chars:
                            cur = f"{cur} {w}".strip()
                        else:
                            if cur:
                                pieces.append(cur)
                            cur = w
                    if cur:
                        pieces.append(cur)

    chunks = []
    buf = ""
    for p in pieces:
        if not buf:
            buf = p
        elif len(buf) + len(p) + 1 <= max_chars:
            buf = f"{buf} {p}"
        else:
            chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    return chunks


def _get_ninada_engine():
    global _NINADA_ENGINE
    if _NINADA_ENGINE is None:
        from ninada import Ninada
        _NINADA_ENGINE = Ninada(lang="bn")
    return _NINADA_ENGINE


def _apply_ninada_postprocess(raw_wav: Path, output_path: Path, tempo: str = "0.92"):
    """Ninada এর স্বাভাবিক স্পিড (atempo=0.92) + স্টুডিও মাস্টারিং প্রয়োগ করে"""
    if not shutil.which("ffmpeg"):
        shutil.copy2(raw_wav, output_path)
        return

    paced_wav = raw_wav.with_suffix(".paced.wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(raw_wav), "-filter:a", f"atempo={tempo}", "-c:a", "pcm_s16le", str(paced_wav)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        src_for_master = paced_wav if (paced_wav.exists() and paced_wav.stat().st_size > 1000) else raw_wav

        out_ext = output_path.suffix.lower()
        codec_args = ["-c:a", "libmp3lame", "-b:a", "192k"] if out_ext == ".mp3" else ["-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le"]

        master_cmd = [
            "ffmpeg", "-y", "-i", str(src_for_master),
            "-af",
            "highpass=f=80,"
            "equalizer=f=250:t=q:w=1.2:g=2.5,"
            "equalizer=f=4500:t=q:w=1.5:g=-3.5,"
            "acompressor=threshold=-18dB:ratio=2.5:attack=10:release=100,"
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            *codec_args,
            str(output_path),
        ]
        res = subprocess.run(master_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1000:
            if out_ext == ".mp3":
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(src_for_master), "-c:a", "libmp3lame", "-b:a", "192k", str(output_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            else:
                shutil.copy2(src_for_master, output_path)
    finally:
        if paced_wav.exists():
            try:
                paced_wav.unlink()
            except Exception:
                pass


def synthesize_with_ninada(speech_text, output_audio_path):
    """একক ভয়েস ইঞ্জিন: Ninada Neural Bengali Male (atempo=0.92 + Studio Mastering)"""
    print("\n--- [VOICE ENGINE: Ninada Neural Bengali Male] ---")
    if not speech_text:
        return False

    out_path = Path(output_audio_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_wav = out_path.with_suffix(".ninada_raw.wav")

    voice = os.environ.get("NINADA_VOICE", "male").strip().lower() or "male"
    tempo = os.environ.get("NINADA_TEMPO", "0.92").strip() or "0.92"
    start_t = time.time()

    try:
        tts = _get_ninada_engine()
        chunks = _split_text_for_ninada(speech_text, max_chars=450)
        print(f"  🎙️ Synthesizing {len(chunks)} chunk(s) with Ninada (voice={voice}, tempo={tempo})...")

        parts = []
        sr_final = 24000
        pause = None

        for idx, chunk in enumerate(chunks):
            wav_bytes = tts.speak(chunk, lang="bn", voice=voice)
            if not wav_bytes or len(wav_bytes) < 100:
                continue
            seg, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
            sr_final = int(sr)
            if pause is None:
                pause = np.zeros(int(sr_final * 0.18), dtype=np.float32)
            parts.append(np.asarray(seg, dtype=np.float32).reshape(-1))
            if idx < len(chunks) - 1:
                parts.append(pause)

        if not parts:
            print("  ❌ Ninada returned empty audio.")
            return False

        merged = np.concatenate(parts) if len(parts) > 1 else parts[0]
        sf.write(str(raw_wav), merged, sr_final, subtype="PCM_16")

        _apply_ninada_postprocess(raw_wav, out_path, tempo=tempo)

        if out_path.exists() and out_path.stat().st_size > 1000:
            dur = round(sf.info(str(out_path)).duration, 1) if out_path.suffix.lower() == ".wav" else 0
            audio_mb = round(out_path.stat().st_size / (1024 * 1024), 2)
            dur_msg = f" | Duration: {dur}s" if dur else ""
            print(f"  ✅ [SUCCESS] Ninada Mastered Audio Ready! ({audio_mb} MB{dur_msg} in {round(time.time() - start_t, 2)}s)")
            return True
    except Exception as e:
        print(f"  ❌ Ninada synthesis error: {e}")
    finally:
        if raw_wav.exists():
            try:
                raw_wav.unlink()
            except Exception:
                pass

    return False


def generate_voiceover_audio_pipeline(text, output_audio_path):
    speech_text = clean_script_for_speech(text)
    clean_chars = len(speech_text)
    words = len(speech_text.split())

    print("\n" + "=" * 65)
    print("🎙️ [AUDIO ENGINE] Ninada Bengali Studio Voice Pipeline")
    print(f"📊 [Script Stats] Chars: {clean_chars} | Words: {words}")
    print("=" * 65)

    return synthesize_with_ninada(speech_text, output_audio_path)
