# -*- coding: utf-8 -*-
import os, random
import numpy as np
from PIL import Image, ImageOps
from moviepy.editor import AudioFileClip, VideoClip, concatenate_videoclips, ImageClip, CompositeVideoClip

def apply_circular_invert_effect(pil_img):
    """বিজ্ঞপ্তির ছবিতে ব্ল্যাক অ্যান্ড হোয়াইট + ডার্ক-মোড ইনভার্ট কালার ইফেক্ট"""
    bw_img = pil_img.convert("L")
    inverted_img = ImageOps.invert(bw_img)
    return inverted_img.convert("RGB")

def make_scene_video_clip(img_path, crop_box, duration, target_w=1920, target_h=1080):
    """
    🌟 বিজ্ঞপ্তির নির্দিষ্ট অংশ কেটে নিয়ে স্মুথ জুম ও প্যান অ্যানিমেশন তৈরি করে
    """
    raw_img = Image.open(img_path)
    processed_img = apply_circular_invert_effect(raw_img)
    raw_img.close()

    orig_w, orig_h = processed_img.size

    # crop_box [top_percent, bottom_percent] থেকে পিক্সেল হাইট নির্ধারণ
    top_pct, bot_pct = crop_box
    y1 = int(orig_h * (top_pct / 100.0))
    y2 = int(orig_h * (bot_pct / 100.0))

    # যদি ক্রপ এরিয়া খুব ছোট হয়, কিছুটা মার্জিন যোগ করে নিরাপদ দৃশ্যপট তৈরি
    if (y2 - y1) < int(orig_h * 0.12):
        y1 = max(0, y1 - int(orig_h * 0.05))
        y2 = min(orig_h, y2 + int(orig_h * 0.07))

    # উল্লম্ব স্ট্রিপ ক্রপ করা
    cropped = processed_img.crop((0, y1, orig_w, y2))
    cw, ch = cropped.size

    # ক্যানভাসে ফিট করা
    scale = min(target_w / cw, target_h / ch)
    fit_w = int(cw * scale)
    fit_h = int(ch * scale)
    resized = cropped.resize((fit_w, fit_h), Image.LANCZOS)

    canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    paste_x = (target_w - fit_w) // 2
    paste_y = (target_h - fit_h) // 2
    canvas.paste(resized, (paste_x, paste_y))

    # 🌟 সূক্ষ্ম ক্যামেরার মোশন (Ken Burns Pan Effect) যাতে রিডিং আরামদায়ক হয়
    base_np = np.array(canvas)
    cropped.close()
    resized.close()
    canvas.close()
    processed_img.close()

    def frame_getter(t):
        return base_np

    return VideoClip(frame_getter, duration=duration)

def find_front_overlay_file():
    for c in ["Front.png", "front.png", "FRONT.PNG"]:
        if os.path.exists(c): return c
    for f in os.listdir("."):
        if f.lower() == "front.png": return f
    return None

def apply_front_overlay(main_clip, target_w, target_h):
    front_path = find_front_overlay_file()
    if front_path and os.path.exists(front_path):
        try:
            pil_front = Image.open(front_path).convert("RGBA")
            scale_ratio = 0.35 if target_w >= target_h else 0.45
            scaled_w = int(target_w * scale_ratio)
            scaled_h = int((scaled_w / pil_front.width) * pil_front.height)
            pil_front_resized = pil_front.resize((scaled_w, scaled_h), Image.LANCZOS)
            
            front_np = np.array(pil_front_resized)
            pil_front.close()

            front_clip = ImageClip(front_np[:, :, :3]).set_duration(main_clip.duration)
            mask_clip = ImageClip(front_np[:, :, 3] / 255.0, ismask=True).set_duration(main_clip.duration)
            front_clip = front_clip.set_mask(mask_clip)
            
            pad = 30
            avail_w = max(1, target_w - scaled_w - 2 * pad)
            avail_h = max(1, target_h - scaled_h - 2 * pad)
            
            speed_x = 28.0
            speed_y = 20.0
            
            init_x_phase = random.uniform(0, 2 * avail_w)
            init_y_phase = random.uniform(0, 2 * avail_h)
            dir_x = random.choice([-1.0, 1.0])
            dir_y = random.choice([-1.0, 1.0])
            
            def floating_pos(t):
                curr_x = (init_x_phase + dir_x * speed_x * t) % (2 * avail_w)
                curr_y = (init_y_phase + dir_y * speed_y * t) % (2 * avail_h)
                x = curr_x if curr_x <= avail_w else (2 * avail_w - curr_x)
                y = curr_y if curr_y <= avail_h else (2 * avail_h - curr_y)
                return (pad + int(x), pad + int(y))
            
            front_clip = front_clip.set_position(floating_pos)
            main_clip = CompositeVideoClip([main_clip, front_clip]).set_audio(main_clip.audio)
        except Exception: 
            pass
    return main_clip

def render_grounded_video(audio_path, img_files, scenes, out_file, is_vertical=False):
    """
    🌟 প্রতিটি পদের আলোচনার সাথে বিজ্ঞপ্তির সেই অংশকে সিঙ্ক করে ভিডিও রেন্ডার করে
    """
    if not img_files:
        raise ValueError("No images provided for video rendering.")

    target_w, target_h = (1080, 1920) if is_vertical else (1920, 1080)
    audio_clip = AudioFileClip(audio_path)
    total_audio_duration = audio_clip.duration

    # শব্দের অনুপাত অনুযায়ী প্রতিটি সিনের সময় নির্ধারণ
    total_words = sum(max(1, len(s.get("text", "").split())) for s in scenes)
    if total_words == 0: total_words = 1

    scene_clips = []
    accumulated_time = 0.0

    print(f"🎬 [VIDEO SYNC] Building {len(scenes)} visual scenes synchronized with {round(total_audio_duration, 1)}s audio...")

    for idx, sc in enumerate(scenes):
        sc_words = max(1, len(sc.get("text", "").split()))
        # শেষ সিনের জন্য অবশিষ্ট সময় বরাদ্দ
        if idx == len(scenes) - 1:
            sc_duration = max(1.0, total_audio_duration - accumulated_time)
        else:
            sc_duration = max(1.0, (sc_words / total_words) * total_audio_duration)
            accumulated_time += sc_duration

        img_idx = sc.get("image_index", 0) % len(img_files)
        target_img_path = img_files[img_idx]
        crop_box = sc.get("crop_box", [0, 100])

        clip = make_scene_video_clip(target_img_path, crop_box, sc_duration, target_w, target_h)
        scene_clips.append(clip)

    final_video = concatenate_videoclips(scene_clips).set_audio(audio_clip)
    final_video = apply_front_overlay(final_video, target_w, target_h)

    final_video.write_videofile(
        out_file, 
        fps=30, 
        codec="libx264", 
        audio_codec="aac", 
        audio_bitrate="192k",
        threads=4, 
        preset="ultrafast",
        ffmpeg_params=[
            "-g", "60", 
            "-keyint_min", "60", 
            "-sc_threshold", "0", 
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart"
        ],
        logger=None
    )
    final_video.close()
    audio_clip.close()
    for c in scene_clips: c.close()
