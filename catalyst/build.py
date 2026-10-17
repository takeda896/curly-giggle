"""Build an episode: narration -> captions -> frames -> mp4 (+ reel, thumbnail, YouTube metadata).

    python -m catalyst.build episodes/ai-power-problem/script.json
"""
import argparse
import hashlib
import json
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter

from . import music
from .render import (ACCENTS, BG, FPS, GRAY, H, TEAL, W, WHITE, bg_frame, draw_rich, fit, font, glow_layer, icon,
                     render_frame, wrap)
from .tts import SR, Narrator, split_sentences

ROOT = Path(__file__).resolve().parent.parent
LEAD, GAP, TAIL, CARD_TAIL = 0.35, 0.3, 0.6, 0.9
RW, RH = 1080, 1920


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


# ---------------------------------------------------------------- narration

def narrate(ep, workdir):
    """Synthesize every sentence (cached), lay scenes out on a frame-exact timeline."""
    cache = workdir / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    narrator = None
    timeline, start = [], 0.0
    clips = []
    for sc in ep["scenes"]:
        is_card = sc["visual"]["type"] == "card"
        pieces, caps, t = [np.zeros(int(LEAD * SR), np.float32)], [], LEAD
        for sent in split_sentences(sc["say"]):
            key = hashlib.sha1(f'{ep["voice"]}|{ep["speed"]}|{sent}'.encode()).hexdigest()[:16]
            wav = cache / f"{key}.wav"
            if not wav.exists():
                narrator = narrator or Narrator(ep["voice"], ep["speed"])
                sf.write(wav, narrator.sentence(sent), SR)
            a, _ = sf.read(wav, dtype="float32")
            caps += chunk_captions(sent, t, len(a) / SR)
            pieces += [a, np.zeros(int(GAP * SR), np.float32)]
            t += len(a) / SR + GAP
        pieces[-1] = np.zeros(int((CARD_TAIL if is_card else TAIL) * SR), np.float32)
        audio = np.concatenate(pieces)
        frames = int(np.ceil(len(audio) / SR * FPS))
        audio = np.pad(audio, (0, int(frames / FPS * SR) - len(audio)))
        dur = frames / FPS
        timeline.append({"id": sc["id"], "start": start, "dur": dur, "frames": frames, "captions": caps})
        clips.append(audio)
        start += dur
    return timeline, clips


def chunk_captions(sentence, t0, dur, maxc=46):
    words, chunks, cur = sentence.split(), [], ""
    for w_ in words:
        if cur and len(cur) + 1 + len(w_) > maxc:
            chunks.append(cur)
            cur = w_
        else:
            cur = (cur + " " + w_).strip()
    chunks.append(cur)
    total = sum(len(c) + 3 for c in chunks)
    out, t = [], t0
    for c in chunks:
        d = dur * (len(c) + 3) / total
        out.append((t, t + d, c))
        t += d
    out[-1] = (out[-1][0], out[-1][1] + GAP, out[-1][2])
    return out


def chapter_labels(ep):
    labels, cur = [], ""
    for sc in ep["scenes"]:
        cur = sc.get("chapter", cur)
        labels.append(cur)
    return labels


# ---------------------------------------------------------------- video

def _render_segment(job):
    scene, tl, seed, label, path, mode, reel = job
    size = f"{RW}x{RH}" if mode == "reel" else f"{W}x{H}"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", size,
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                          "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)
    for f in range(tl["frames"]):
        t = f / FPS
        if mode == "reel":
            img = reel_frame(scene, t, tl, seed, label, reel)
        else:
            img = render_frame(scene, t, tl["dur"], seed, label, tl["captions"])
        p.stdin.write(img.tobytes())
    p.stdin.close()
    assert p.wait() == 0, f"ffmpeg failed for {path}"
    return path


def render_video(ep, scenes, timeline, labels, workdir, name, mode="main", procs=4):
    segdir = workdir / f"seg_{name}"
    segdir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for i, (sc, tl, lab) in enumerate(zip(scenes, timeline, labels)):
        seed = ep["scenes"].index(sc)
        jobs.append((sc, tl, seed, lab, segdir / f"{i:03d}_{sc['id']}.mp4", mode, ep.get("reel")))
    with Pool(procs) as pool:
        for k, path in enumerate(pool.imap(_render_segment, jobs), 1):
            print(f"  [{name}] {k}/{len(jobs)} {path.name}", flush=True)
    lst = segdir / "list.txt"
    lst.write_text("".join(f"file '{j[4].name}'\n" for j in jobs))
    silent = workdir / f"{name}_video.mp4"
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent))
    return silent


def mix_audio(narration, swells, workdir, name, music_gain=0.11):
    nar = workdir / f"{name}_narration.wav"
    sf.write(nar, narration, SR)
    secs = len(narration) / SR
    bed = workdir / f"{name}_music.wav"
    sf.write(bed, music.bed(secs, swells), music.SR)
    out = workdir / f"{name}_mix.wav"
    ffmpeg("-i", str(nar), "-i", str(bed), "-filter_complex",
           f"[0]aresample=48000,asplit[n1][n2];[1]volume={music_gain}[m];"
           "[m][n1]sidechaincompress=threshold=0.04:ratio=3:attack=20:release=400[md];"
           "[n2][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11",
           "-ar", "48000", str(out))
    return out


def mux(video, audio, out):
    ffmpeg("-i", str(video), "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out))


# ---------------------------------------------------------------- reel

def reel_frame(scene, t, tl, seed, label, reel):
    box = render_frame(scene, t, tl["dur"], seed, label, with_captions=False)
    acc = ACCENTS.get(scene["visual"].get("accent", "teal"), TEAL)
    bg = box.resize((96, 54), Image.BILINEAR).filter(ImageFilter.GaussianBlur(3)).resize((RW * 2, RH), Image.BILINEAR)
    bg = bg.crop((RW // 2, 0, RW // 2 + RW, RH))
    img = Image.blend(Image.new("RGB", (RW, RH), BG), bg, 0.45).convert("RGBA")
    bw, bh = RW, int(RW * H / W)
    by = 600
    img.paste(box.resize((bw, bh), Image.LANCZOS), (0, by))
    d = ImageDraw.Draw(img)
    heads = reel["headline"]
    hf = fit("head", 110, heads, RW - 120)
    for i, line in enumerate(heads):
        draw_rich(d, (RW / 2, 230 + i * (hf.size + 12)), line, hf, WHITE, acc, 1.0)
    from .render import caption_at
    cap = caption_at(tl["captions"], t)
    if cap:
        cf = font("xbold", 54)
        for i, line in enumerate(wrap(cap, cf, RW - 140)):
            d.text((RW / 2, by + bh + 50 + i * 70), line, font=cf, fill=(*WHITE, 255), anchor="mt",
                   stroke_width=4, stroke_fill=(0, 0, 0, 255))
    cta = reel["cta"]
    d.text((RW / 2, 1520), cta[0], font=fit("head4", 60, [cta[0]], RW - 120), fill=(*WHITE, 255), anchor="mt")
    d.text((RW / 2, 1610), cta[1], font=font("head4", 46), fill=(*acc, 255), anchor="mt")
    d.text((RW / 2, 1760), "THE CATALYST", font=font("head4", 34), fill=(*GRAY, 255), anchor="mt")
    return img.convert("RGB")


# ---------------------------------------------------------------- thumbnail & metadata

def thumbnail(ep, path):
    th = ep["thumbnail"]
    img = bg_frame(3, TEAL, 0).convert("RGBA")
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    icon(d, th.get("icon", "bolt"), 1480, 620, 600, 1.0, 0.4, TEAL)
    icon(d, "bolt", 1480, 660, 300, 1.0, 0.0, TEAL)
    layer = glow_layer(layer, (1000, 150, 1920, 1000), radius=60, strength=0.6)
    d = ImageDraw.Draw(layer)
    hf = fit("head", 220, th["lines"], 1150)
    for i, line in enumerate(th["lines"]):
        draw_rich(d, (110, 250 + i * (hf.size + 10)), line, hf, WHITE, TEAL, 1.0, anchor="l")
    tf = font("head", 90)
    tw = tf.getlength(th["tag"])
    d.rounded_rectangle([110, 760, 110 + tw + 70, 880], radius=18, fill=(255, 77, 90, 255))
    d.text((145, 760), th["tag"], font=tf, fill=(255, 255, 255, 255))
    img = Image.alpha_composite(img, layer).convert("RGB")
    img.resize((1280, 720), Image.LANCZOS).save(path, quality=92)


def fmt_ts(sec):
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}" if sec < 3600 else f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def metadata(ep, timeline, total, path):
    chapters = []
    for sc, tl in zip(ep["scenes"], timeline):
        if sc.get("chapter"):
            chapters.append(f'{fmt_ts(tl["start"])} {sc["chapter"]}')
    tags = " ".join("#" + h for h in ep["hashtags"])
    desc = f'{ep["description"]}\n\n' + "\n".join(chapters) + f"\n\n\n{tags}"
    path.write_text(f'TITLE:\n{ep["title"]}\n\nDURATION: {fmt_ts(total)}\n\nDESCRIPTION:\n{desc}\n')
    return desc


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--only", choices=["main", "reel", "thumb"], help="build just one output")
    args = ap.parse_args()
    ep = json.loads(Path(args.script).read_text())
    out = ROOT / "out" / ep["slug"]
    out.mkdir(parents=True, exist_ok=True)

    print("1/4 narration", flush=True)
    timeline, clips = narrate(ep, out)
    labels = chapter_labels(ep)
    total = sum(t["dur"] for t in timeline)
    print(f"    {len(timeline)} scenes, {fmt_ts(total)}", flush=True)
    meta = metadata(ep, timeline, total, out / "youtube.txt")

    if args.only in (None, "thumb"):
        thumbnail(ep, out / "thumbnail.jpg")

    if args.only in (None, "main"):
        print("2/4 main video", flush=True)
        video = render_video(ep, ep["scenes"], timeline, labels, out, "main", procs=args.procs)
        swells = [t["start"] + 0.2 for sc, t in zip(ep["scenes"], timeline) if sc["visual"]["type"] == "card"]
        mux(video, mix_audio(np.concatenate(clips), swells, out, "main"), out / f'{ep["slug"]}.mp4')

    if args.only in (None, "reel") and ep.get("reel"):
        print("3/4 reel", flush=True)
        reel = ep["reel"]
        idx = [next(i for i, s in enumerate(ep["scenes"]) if s["id"] == rid) for rid in reel["scenes"]]
        while sum(timeline[i]["dur"] for i in idx) > reel.get("max_seconds", 59) and len(idx) > 1:
            idx.pop()
        scenes = [ep["scenes"][i] for i in idx]
        tls = [timeline[i] for i in idx]
        video = render_video(ep, scenes, tls, [labels[i] for i in idx], out, "reel", mode="reel", procs=args.procs)
        mux(video, mix_audio(np.concatenate([clips[i] for i in idx]), [], out, "reel"), out / f'{ep["slug"]}_reel.mp4')
        print(f"    reel: {', '.join(s['id'] for s in scenes)} ({sum(t['dur'] for t in tls):.1f}s)")

    print("4/4 done ->", out, flush=True)
    print(meta[:300] + "...", flush=True)


if __name__ == "__main__":
    sys.exit(main())
