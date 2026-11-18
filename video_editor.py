# -*- coding: utf-8 -*-
import os, random
import numpy as np
from PIL import Image, ImageOps
from moviepy.editor import AudioFileClip, VideoClip, concatenate_videoclips, ImageClip, CompositeVideoClip


def _trim_white_margins(pil_img, pad=24):
    """স্ক্যান করা সার্কুলারের নিচের/পাশের বাড়তি খালি সাদা অংশ ক্রপ করে, যাতে ইনভার্ট করার পর ৪০ সেকেন্ড কালো স্ক্রিন না থাকে"""
    rgb = pil_img.convert("RGB")
    arr = np.asarray(rgb)
    # যে পিক্সেলগুলোতে লেখা/দাগ আছে (brightness < 235) সেগুলো খুঁজে বের করা
    non_white = np.any(arr < 235, axis=2)
    coords = np.argwhere(non_white)
    if coords.size == 0:
        return rgb
    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0) + 1
    h, w = arr.shape[:2]
    x0 = max(0, int(x0) - pad)
    y0 = max(0, int(y0) - pad)
    x1 = min(w, int(x1) + pad)
    y1 = min(h, int(y1) + pad)
    if (x1 - x0) >= w * 0.4 and (y1 - y0) >= h * 0.25:
        return rgb.crop((x0, y0, x1, y1))
    return rgb


def apply_circular_invert_effect(pil_img):
    """বিজ্ঞপ্তির ছবিতে ব্ল্যাক অ্যান্ড হোয়াইট + ডার্ক-মোড ইনভার্ট কালার ইফেক্ট (আগের ডিজাইন অপরিবর্তিত)"""
    trimmed = _trim_white_margins(pil_img, pad=24)
    bw_img = trimmed.convert("L")
    inverted_img = ImageOps.invert(bw_img)
    return inverted_img.convert("RGB")


def make_video_frame(img_path, duration, target_w=1920, target_h=1080):
    """
    🌟 বিজ্ঞপ্তির ছবিটিকে উপর থেকে নিচে মসৃণভাবে স্ক্রল (Scroll / Pan-and-Scan) করানোর ফ্রেম জেনারেটর
    """
    with Image.open(img_path) as pil_raw:
        pil_img = apply_circular_invert_effect(pil_raw)

    w, h = pil_img.size
    ratio = w / float(h or 1)

    if target_w < target_h:
        # ৯:১৬ পোর্ট্রেট ভিডিও (JobLive / Shorts)
        if ratio < (9.0 / 16.0) - 0.01:
            new_w = target_w
            new_h = max(target_h, int(round((target_w / w) * h)))
            img_np = np.array(pil_img.resize((new_w, new_h), Image.LANCZOS))
            max_offset = max(0, new_h - target_h)
            def frame_getter(t):
                prog = min(1.0, max(0.0, t / duration if duration > 0 else 0))
                y_start = int(prog * max_offset)
                return img_np[y_start : y_start + target_h, 0:target_w]
            clip = VideoClip(frame_getter, duration=duration)
        elif (9.0 / 16.0) - 0.01 <= ratio < (16.0 / 9.0) - 0.01:
            scale = min(target_w / w, target_h / h)
            rw, rh = int(round(w * scale)), int(round(h * scale))
            resized = pil_img.resize((rw, rh), Image.LANCZOS)
            canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
            canvas.paste(resized, ((target_w - rw) // 2, (target_h - rh) // 2))
            img_np = np.array(canvas)
            clip = VideoClip(lambda t: img_np, duration=duration)
        else:
            new_h = target_h
            new_w = max(target_w, int(round((target_h / h) * w)))
            img_np = np.array(pil_img.resize((new_w, new_h), Image.LANCZOS))
            max_offset = max(0, new_w - target_w)
            def frame_getter(t):
                prog = min(1.0, max(0.0, t / duration if duration > 0 else 0))
                x_start = int(prog * max_offset)
                return img_np[0:target_h, x_start : x_start + target_w]
            clip = VideoClip(frame_getter, duration=duration)
    else:
        # ১৬:৯ ল্যান্ডস্কেপ ভিডিও (Regular YouTube Video)
        scale = max(target_w / float(w), target_h / float(h))
        new_w = max(target_w, int(round(w * scale)))
        new_h = max(target_h, int(round(h * scale)))

        img_np = np.array(pil_img.resize((new_w, new_h), Image.LANCZOS))
        max_y_offset = max(0, new_h - target_h)
        max_x_offset = max(0, new_w - target_w)

        def frame_getter(t):
            prog = min(1.0, max(0.0, t / duration if duration > 0 else 0))
            y_start = int(prog * max_y_offset)
            x_start = int(prog * max_x_offset)
            return img_np[y_start : y_start + target_h, x_start : x_start + target_w]

        clip = VideoClip(frame_getter, duration=duration)

    pil_img.close()
    return clip


def find_front_overlay_file():
    for c in ["Front.png", "front.png", "FRONT.PNG"]:
        if os.path.exists(c):
            return c
    for f in os.listdir("."):
        if f.lower() == "front.png":
            return f
    return None


def apply_front_overlay(main_clip, target_w, target_h):
    front_path = find_front_overlay_file()
    if front_path and os.path.exists(front_path):
        try:
            pil_front = Image.open(front_path).convert("RGBA")
            scale_ratio = 0.23 if target_w >= target_h else 0.34
            scaled_w = int(target_w * scale_ratio)
            scaled_h = int((scaled_w / pil_front.width) * pil_front.height)
            pil_front_resized = pil_front.resize((scaled_w, scaled_h), Image.LANCZOS)

            front_np = np.array(pil_front_resized)
            pil_front.close()

            front_clip = ImageClip(front_np[:, :, :3]).set_duration(main_clip.duration)
            mask_clip = ImageClip((front_np[:, :, 3] / 255.0) * 0.85, ismask=True).set_duration(main_clip.duration)
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


def render_video_slideshow(audio_path, img_files, out_file, is_vertical=False):
    """
    🌟 পুরো অডিওর সময়কালকে ছবির মধ্যে ভাগ করে উপর থেকে নিচে মসৃণ স্ক্রলিং স্লাইডশো তৈরি করে
    """
    if not img_files:
        raise ValueError("No images provided for slideshow rendering.")

    target_w, target_h = (1080, 1920) if is_vertical else (1920, 1080)
    audio_clip = AudioFileClip(audio_path)
    per_img_duration = audio_clip.duration / len(img_files)

    print(f"🎬 [SLIDESHOW] Rendering {len(img_files)} scrolling images (Total: {round(audio_clip.duration, 1)}s)...")

    clips = [make_video_frame(v, per_img_duration, target_w, target_h) for v in img_files]
    final_video = concatenate_videoclips(clips).set_audio(audio_clip)
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
    for c in clips:
        c.close()


# ব্যাকওয়ার্ড কম্প্যাটিবিলিটির জন্য অ্যালিয়াস
render_synchronized_video = render_video_slideshow
