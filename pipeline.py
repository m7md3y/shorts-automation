def scene_video_visual(srcs, audio, dur_s, idx, workdir, w, h, role="norm", sfx=None, overlays=None, whoosh=None, suspense=None):
    overlays = overlays or []
    out = workdir / f"scene_{idx:02d}.mp4"
    k = len(srcs)
    share = dur_s / k
    cmd = [str(FFMPEG), "-y"]
    fc = []
    labels = []
    for j, p in enumerate(srcs):
        cmd += ["-i", p.name]
        fr = max(int(share * 30) + 2, 8)
        zin = (idx + j) % 2 == 0
        z = f"min(1+0.08*on/{fr},1.08)" if zin else f"max(1.08-0.08*on/{fr},1.0)"
        fc.append(
            f"[{j}:v]scale={int(w * 1.35)}:{int(h * 1.35)}:flags=lanczos+full_chroma_int,"
            f"unsharp=lx=5:ly=5:la=0.9:cx=3:cy=3:ca=0.35,"
            f"zoompan=z='{z}':d={fr}:x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':s={w}x{h}:fps=30,"
            f"setsar=1,fps=30,trim=duration={share:.2f},setpts=PTS-STARTPTS[v{j}]"
        )
        labels.append(f"[v{j}]")
    next_idx = k
    cmd += ["-i", audio.name]
    fc.append(f"[{next_idx}:a]anull[a0]")
    amix = ["[a0]"]
    next_idx += 1
    if sfx is not None:
        cmd += ["-i", sfx.name]
        fc.append(f"[{next_idx}:a]volume=0.85[bs]")
        amix.append("[bs]")
        next_idx += 1
    if whoosh is not None:
        cmd += ["-i", whoosh.name]
        fc.append(f"[{next_idx}:a]volume=0.6[wh]")
        amix.append("[wh]")
        next_idx += 1
    if suspense is not None and role in ("norm", "outro"):
        cmd += ["-i", suspense.name]
        fc.append(f"[{next_idx}:a]volume=0.3,atrim=duration=2.0[sp]")
        amix.append("[sp]")
        next_idx += 1
    if k > 1:
        fc.append("".join(labels) + f"concat=n={k}:v=1:a=0[vc]")
        vbase = "[vc]"
    else:
        vbase = labels[0]
    cur_v = vbase
    for j, ov in enumerate(overlays):
        st = min(0.55 + j * 2.4, max(dur_s - 2.1, 0.55))
        en = min(st + 1.9, dur_s - 0.15)
        side = "main_w-overlay_w-50" if (idx + j) % 2 == 0 else "50"
        ypos = f"main_h*{0.11 + 0.05 * j:.2f}"
        cmd += ["-i", ov.name]
        fc.append(
            f"[{next_idx}:v]scale=520:520:force_original_aspect_ratio=increase:flags=lanczos,unsharp=5:5:0.6,crop=520:520,"
            f"pad=iw+14:ih+14:7:7:color=white,"
            f"fade=t=in:st={st:.2f}:d=0.18:alpha=1,fade=t=out:st={en - 0.18:.2f}:d=0.18:alpha=1,"
            f"setpts=PTS-STARTPTS[o{j}]"
        )
        nxt = f"[c{j}]"
        fc.append(f"{cur_v}[o{j}]overlay=x={side}:y={ypos}:enable='between(t,{st:.2f},{en:.2f})'{nxt}")
        cur_v = nxt
        next_idx += 1
        cmd += ["-i", "pop.wav"]
        ms = int(st * 1000)
        fc.append(f"[{next_idx}:a]adelay={ms}|{ms},volume=0.4[p{j}]")
        amix.append(f"[p{j}]")
        next_idx += 1
    fc.append("".join(amix) + f"amix=inputs={len(amix)}:duration=first:normalize=0[a]")
    cmd += [
        "-filter_complex", ";".join(fc),
        "-map", cur_v, "-map", "[a]",
        "-t", f"{dur_s:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-shortest", "-movflags", "+faststart",
        out.name,
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=900, cwd=str(workdir))
    return out


import difflib
import datetime
import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

import requests

BASE = pathlib.Path(__file__).parent
if os.name == "nt":
    FFMPEG = BASE / "ffmpeg-9.0.1-essentials_build" / "bin" / "ffmpeg.exe"
    FFPROBE = BASE / "ffmpeg-9.0.1-essentials_build" / "bin" / "ffprobe.exe"
else:
    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"
GEMINI_MODELS = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3-flash-preview", "gemini-3.5-flash-lite"]
PEXELS_URL = "https://api.pexels.com/videos/search"

CATEGORIES = {
    "explained": {
        "name": "Explained",
        "name_ar": "مُفسَّر",
        "prompt_suffix": "Focus on strange feelings, brain tricks, psychology facts, human behavior anomalies. The viewer should feel 'I never knew this!'",
        "visual_style": "psychology, brain scans, human behavior, close-up faces, abstract neural networks",
        "tone": "fascinated, revealing, mind-blowing",
        "hashtag": "#psychology #brainfacts #explained #humanbehavior",
    },
    "mystery": {
        "name": "Mysterious Stories",
        "name_ar": "قصص غامضة",
        "prompt_suffix": "Focus on historical mysteries, unexplained events, cold cases, strange disappearances, ancient secrets. Build suspense and tension.",
        "visual_style": "dark atmosphere, mysterious locations, historical settings, shadows, fog, ancient artifacts",
        "tone": "suspenseful, mysterious, dark",
        "hashtag": "#mystery #unsolved #darkstories #historicalmystery",
    },
    "whatif": {
        "name": "What If",
        "name_ar": "ماذا لو",
        "prompt_suffix": "Focus on dangerous survival scenarios: lost in forest/desert/ocean, natural disasters, emergency situations. Include survival tips and end with safety advice.",
        "visual_style": "danger, survival, nature extremes, wilderness, desert, ocean, emergency equipment",
        "tone": "urgent, survival, educational",
        "hashtag": "#whatif #survival #danger #safetytips",
    },
}

BANNED_PATTERNS = [
    r"you won'?t believe",
    r"doctors hate",
    r"goes viral",
    r"\bguaranteed\b",
    r"\d{1,3}\s?%",
    r"study (shows|proves|found)",
    r"scientists (hate|found)",
]


class RunLog:
    def __init__(self, stage_tag="run"):
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.path = BASE / "logs" / f"{stage_tag}_{ts}.log"
        self.path.parent.mkdir(exist_ok=True)

    def __call__(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


log = RunLog()


def load_config():
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    for env_key, cfg_key in (("GEMINI_API_KEY", "gemini_api_key"), ("POLLINATIONS_KEY", "pollinations_key")):
        if os.environ.get(env_key):
            cfg[cfg_key] = os.environ[env_key]
    return cfg


def read_json_list(name):
    p = BASE / name
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8-sig"))
    return []


def append_json_list(name, item, cap=200):
    data = read_json_list(name)
    data.append(item)
    p = BASE / name
    p.write_text(json.dumps(data[-cap:], ensure_ascii=False, indent=1), encoding="utf-8")


def script_qc(data, cfg):
    problems = []
    scenes = data.get("scenes", [])
    if len(scenes) < 3:
        problems.append("too few scenes (need at least 3)")
        return problems
    texts = [data["hook"]] + [s["text"] for s in scenes]
    full = " ".join(texts)
    words = len(full.split())
    if not 50 <= words <= 160:
        problems.append(f"word count {words} outside 50-160")
    if len(data["hook"].split()) > 14:
        problems.append("hook too long")
    low = full.lower()
    for pat in BANNED_PATTERNS:
        if re.search(pat, low):
            problems.append(f"banned pattern: {pat}")
    last_sentence = texts[-1].lower()
    if not any(k in last_sentence for k in ["try", "notice", "next time", "remember", "today", "start", "ask", "watch", "loop", "back", "again", "begin"]):
        pass  # loop ending style - no strict takeaway required
    past = read_json_list("used_scripts.json")
    for old in past[-30:]:
        ratio = difflib.SequenceMatcher(None, full.lower(), old.lower()).ratio()
        if ratio > 0.6:
            problems.append(f"too similar to previous script ({ratio:.2f})")
            break
    return problems


def pick_best_hook(api_key, title, scenes_summary, candidates):
    cands = "\n".join(f"{n + 1}. {c}" for n, c in enumerate(candidates))
    prompt = f"""You are a ruthless YouTube Shorts retention expert. Video title: {title}
Story: {scenes_summary}

Hook candidates:
{cands}

Score each hook 1-10 on: instant curiosity gap, emotional punch, stop-the-scroll power, simplicity, truthfulness.
Think briefly, then answer with ONLY the NUMBER of the winner."""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800, "thinkingConfig": {"thinkingBudget": 0}},
    }
    for model in GEMINI_MODELS:
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": api_key}, json=body, timeout=90)
            if r.ok:
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                m = re.search(r"\b(\d+)\b", txt)
                if m:
                    idx = int(m.group(1)) - 1
                    if 0 <= idx < len(candidates):
                        return candidates[idx]
        except Exception as e:
            log(f"  hook-judge {model}: {e}")
        time.sleep(2)
    return candidates[0]


def gemini_script(api_key, niche, category="explained"):
    used_titles = read_json_list("used_topics.json")
    titles_str = "\n".join(used_titles[-40:]) if used_titles else "none"
    cat = CATEGORIES.get(category, CATEGORIES["explained"])

    prompt = f"""You are the world's highest-retention YouTube Shorts writer. Your scripts have generated billions of views.

CATEGORY: {cat['name']} ({cat['name_ar']})
STYLE: {cat['prompt_suffix']}
TONE: {cat['tone']}

Topics already used (never repeat):
{titles_str}

STEP 1 — IDEA SELECTION: Brainstorm 10 ideas for the {cat['name']} category. Choose the ONE with historically proven massive engagement on Shorts. It must be truthful, fascinating, and VISUAL (easy to show in video).

STEP 2 — SCRIPT: Write with GRIPPING language: power verbs, concrete images, zero filler. Every sentence earns the next second of attention.

Return ONLY valid JSON exactly like:
{{
  "title": "SEO title under 70 chars starting with a search keyword",
  "description": "2 keyword-rich sentences + exactly 4 hashtags",
  "tags": ["psychology", "human behavior", "brain facts", "shorts"],
  "hook": "your single best hook (also included in hook_candidates)",
  "hook_candidates": ["8 different hooks, each max 8 words, each a different angle"],
  "scenes": [
    {{"text": "narration max 15 words", "visuals": ["concrete visual 1", "concrete visual 2"], "overlays": []}}
  ]
}}

STRICT rules:
- Number of scenes: 6 to 10 depending on story needs.
- Total narration words: 90-150. Detailed storytelling.
- The LAST scene must use the SAME visual concept as the first scene (loop ending).
- 8 hook_candidates: max 8 words each, punchy, instant curiosity gap.
- scenes[0].text must CONTINUE after the hook.
- visuals per scene: 1 to 3 concrete, specific, visual queries.
- Use straight apostrophes only.
- SEO title: start with searchable keywords.
- tags: 5-8 lowercase search terms.
- No fabricated statistics or medical claims.
- {cat['prompt_suffix']}"""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.05, "responseMimeType": "application/json"},
    }
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            r = requests.post(url, params={"key": api_key}, json=body, timeout=90)
            if r.ok:
                data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                log(f"SCRIPT via {model} [{cat['name']}]")
                break
        except Exception as e:
            log(f"  {model}: {e}")
            time.sleep(3)
    else:
        raise RuntimeError("all gemini models failed")
    cands = data.get("hook_candidates") or []
    if len(cands) >= 3:
        summary = " ".join(s.get("text", "") for s in data.get("scenes", []))[:300]
        data["hook"] = pick_best_hook(api_key, data.get("title", ""), summary, cands[:10])
        log(f"HOOK WINNER: {data['hook']}")
    return data


def fetch_openverse(query, out_path):
    try:
        r = requests.get(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "page_size": 12, "aspect_ratio": "tall"},
            headers={"User-Agent": "Mozilla/5.0 (ShortsAutomation)"},
            timeout=60,
        )
        if not r.ok:
            return False
        results = [
            x for x in r.json().get("results", [])
            if (x.get("width") or 0) >= 640 and (x.get("height") or 0) >= 860 and x.get("url")
        ]
        random.shuffle(results)
        for im in results[:4]:
            try:
                d = requests.get(
                    im["url"], timeout=180,
                    headers={"User-Agent": "Mozilla/5.0 (ShortsAutomation)"},
                ).content
                if len(d) > 30000:
                    out_path.write_bytes(d)
                    return True
            except Exception:
                continue
    except Exception as e:
        log(f"  openverse: {e}")
    return False


CF_TOKEN = os.environ.get("CF_TOKEN", "")
CF_ACCOUNT = os.environ.get("CF_ACCOUNT", "")
CF_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run"


def gen_image_cloudflare(prompt, out_path, width=720, height=1280):
    try:
        r = requests.post(
            f"{CF_URL}/@cf/black-forest-labs/flux-2-klein-4b",
            headers={"Authorization": f"Bearer {CF_TOKEN}"},
            data={"prompt": prompt, "width": str(width), "height": str(height)},
            timeout=300,
        )
        d = r.json()
        if d.get("success"):
            import base64
            img = base64.b64decode(d["result"]["image"])
            if len(img) > 10000:
                out_path.write_bytes(img)
                return True
        log(f"  cloudflare: {d.get('errors', ['unknown'])[:100]}")
    except Exception as e:
        log(f"  cloudflare: {e}")
    return False


def verify_image(path, min_w=500, min_h=780, min_size_kb=30):
    if not path.exists():
        return False
    if path.stat().st_size < min_size_kb * 1024:
        return False
    try:
        r = subprocess.run(
            [str(FFPROBE), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        parts = r.stdout.strip().split(",")
        if len(parts) >= 2:
            w, h = int(parts[0]), int(parts[1])
            return w >= min_w and h >= min_h
    except Exception:
        pass
    return False


def gen_image_openverse(query, out_path):
    try:
        r = requests.get(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "page_size": 10, "aspect_ratio": "tall"},
            headers={"User-Agent": "Mozilla/5.0 (ShortsAutomation)"},
            timeout=60,
        )
        if not r.ok:
            return False
        results = [
            x for x in r.json().get("results", [])
            if (x.get("width") or 0) >= 500 and (x.get("height") or 0) >= 780 and x.get("url")
        ]
        random.shuffle(results)
        for im in results[:3]:
            try:
                d = requests.get(im["url"], timeout=120, headers={"User-Agent": "Mozilla/5.0"}).content
                if len(d) > 30000:
                    out_path.write_bytes(d)
                    if verify_image(out_path):
                        return True
            except Exception:
                continue
    except Exception as e:
        log(f"  openverse: {e}")
    return False


def gen_image_fallback(query, out_path, seed):
    tail = ", photorealistic, ultra sharp, crisp details, professional photography, natural lighting, high contrast"
    url = (
        "https://image.pollinations.ai/prompt/"
        + urllib.parse.quote(query + tail)
        + f"?width=720&height=1280&nologo=true&model=flux&seed={seed}"
    )
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=180)
            ct = r.headers.get("content-type", "")
            if r.status_code == 200 and "image" in ct and len(r.content) > 10000:
                tmp = out_path.with_suffix(".tmp")
                tmp.write_bytes(r.content)
                import shutil
                shutil.move(str(tmp), str(out_path))
                if verify_image(out_path):
                    return True
        except Exception as e:
            log(f"  fallback retry {attempt + 1}: {e}")
        time.sleep(5 * (attempt + 1))
    return False


def gen_image_smart(prompt, out_path, seed):
    if gen_image_cloudflare(prompt, out_path) and verify_image(out_path):
        return True
    log("  cloudflare failed, trying pollinations hd")
    key = load_config().get("pollinations_key", "")
    if key:
        try:
            tail = ", photorealistic, ultra sharp, crisp details"
            url = "https://gen.pollinations.ai/image/" + urllib.parse.quote(prompt + tail) + f"?width=720&height=1280&model=flux&nologo=true&seed={seed}"
            r = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=300)
            if r.status_code == 200 and "image" in r.headers.get("content-type", "") and len(r.content) > 10000:
                out_path.write_bytes(r.content)
                if verify_image(out_path):
                    return True
        except Exception:
            pass
    log("  pollinations hd failed, trying openverse")
    if gen_image_openverse(prompt.split(",")[0], out_path):
        return True
    log("  openverse failed, trying pollinations free")
    return gen_image_fallback(prompt, out_path, seed)


ENHANCE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"
_enh_cache = {}


def enhance_prompt(query, scene_text, topic):
    ck = (query, scene_text)
    if ck in _enh_cache:
        return _enh_cache[ck]
    api_key = load_config().get("gemini_api_key", "")
    if not api_key:
        return query
    instruction = f"""You are an award-winning cinematographer and photo director preparing a shot for a vertical 9:16 (720x1280) photorealistic image. Describe EVERY pixel: subject details, clothing texture, skin tone, eye direction, finger placement, background bokeh, light rays, dust particles, color grading.

STORY CONTEXT: {topic}
NARRATION LINE: {scene_text}
RAW SHOT IDEA: {query}

Rewrite the raw shot idea into ONE rich English image prompt (60-110 words). Specify precisely:
- exact subject: age, appearance, clothing, facial expression, body pose, what they are doing
- setting details: location specifics, key props and where they sit in frame
- composition: vertical framing, subject placement (rule of thirds), foreground/midground/background layers
- camera: lens feel (35mm/50mm), angle (eye-level/low/high), depth of field
- lighting: type, direction, mood, color temperature
- color palette and atmosphere matching the narration's emotion

Rules: photorealistic photography only. No text/watermarks/logos in image. No camera gear jargon beyond lens feel. Output ONLY the final prompt text, nothing else."""
    body = {
        "contents": [{"parts": [{"text": instruction}]}],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 900,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    for model in GEMINI_MODELS:
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": api_key}, json=body, timeout=90)
            if r.ok:
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip().strip('"')
                if 40 < len(txt) < 900:
                    _enh_cache[ck] = txt
                    return txt
        except Exception as e:
            log(f"  enhance {model}: {e}")
        time.sleep(2)
    return query


def fetch_pexels_clip(query, out_path, api_key, min_dur=4):
    if not api_key:
        return False
    try:
        r = requests.get(
            PEXELS_URL,
            headers={"Authorization": api_key},
            params={"query": query, "orientation": "portrait", "per_page": 10},
            timeout=60,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
        candidates = []
        for v in videos:
            if v.get("duration", 0) < min_dur:
                continue
            for f in v.get("video_files", []):
                w, h = f.get("width", 0), f.get("height", 0)
                if h > w and 720 <= h <= 2160 and f.get("file_type") == "video/mp4":
                    candidates.append((abs(h - 1920), f["link"]))
        if not candidates:
            return False
        candidates.sort()
        dl = requests.get(candidates[0][1], timeout=240)
        if dl.status_code == 200 and len(dl.content) > 50000:
            out_path.write_bytes(dl.content)
            return True
    except Exception as e:
        log(f"  pexels error: {e}")
    return False


def tts_words(text, out_base, voice, rate, pitch="+0Hz"):
    import asyncio

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    import edge_tts as ett

    text = re.sub(r"[,;:\u2014\u2013\u2026()\"]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    mp3 = out_base.with_suffix(".mp3")
    wj = out_base.with_suffix(".words.json")

    async def _gen():
        words = []
        comm = ett.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
        with open(mp3, "wb") as f:
            async for ch in comm.stream():
                t = ch.get("Type") or ch.get("type")
                if t == "audio":
                    f.write(ch.get("Data") or ch.get("data"))
                elif t == "WordBoundary":
                    off = (ch.get("Offset") or ch.get("offset") or 0) / 1e7
                    dur = (ch.get("Duration") or ch.get("duration") or 0) / 1e7
                    wd = ch.get("Text") or ch.get("text") or ""
                    if wd.strip():
                        words.append([wd, off, off + dur])
        return words

    for attempt in range(4):
        try:
            words = asyncio.run(_gen())
            if mp3.exists() and mp3.stat().st_size > 800 and words:
                wj.write_text(json.dumps(words), encoding="utf-8")
                return True
        except Exception as e:
            log(f"  tts retry {attempt + 1}: {e}")
        time.sleep(3 * (attempt + 1))
    return False


SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_word_srt(srt_path):
    words = []
    blocks = re.split(r"\n\s*\n", srt_path.read_text(encoding="utf-8-sig").strip())
    for b in blocks:
        m = SRT_TIME.search(b)
        lines = [l for l in b.strip().splitlines() if l.strip()]
        if not m or len(lines) < 3:
            continue
        word = lines[2].strip()
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
        if word:
            words.append((word, start, end))
    return words


def media_dur(path):
    r = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def process_voice(mp3_in, workdir, idx):
    out = workdir / f"vox_{idx:02d}.mp3"
    af = (
        "highpass=f=70,"
        "acompressor=threshold=0.28:ratio=3.5:attack=8:release=180:makeup=7,"
        "aecho=0.55:0.4:48:0.18,"
        "equalizer=f=220:t=q:w=1:g=2,equalizer=f=3200:t=q:w=1.4:g=1.5,"
        "loudnorm=I=-10:TP=-1.0:LRA=6,"
        "volume=2.5dB,"
        "alimiter=limit=0.92"
    )
    subprocess.run(
        [str(FFMPEG), "-y", "-i", str(mp3_in), "-af", af, "-ar", "44100", "-ac", "2", "-b:a", "192k", str(out)],
        check=True, capture_output=True, timeout=300,
    )
    return out


def make_boom(workdir):
    out = workdir / "boom.wav"
    subprocess.run(
        [str(FFMPEG), "-y", "-f", "lavfi",
         "-i", "sine=frequency=52:duration=1.0",
         "-f", "lavfi", "-i", "anoisesrc=color=brown:duration=0.35:amplitude=0.35",
         "-filter_complex", "[0:a]afade=t=out:st=0.08:d=0.9:curve=exp,volume=13dB[b];[1:a]afade=t=out:st=0.02:d=0.3,volume=9dB[n];[b][n]amix=inputs=2:duration=longest:normalize=0,lowpass=f=300",
         "-ac", "2", "-ar", "44100", str(out)],
        check=True, capture_output=True, timeout=120,
    )
    return out


def make_pop(workdir):
    out = workdir / "pop.wav"
    subprocess.run(
        [str(FFMPEG), "-y", "-f", "lavfi",
         "-i", "sine=frequency=640:duration=0.10",
         "-af", "afade=t=out:st=0.01:d=0.09:curve=exp,volume=9dB,highpass=f=200",
         "-ac", "2", "-ar", "44100", str(out)],
        check=True, capture_output=True, timeout=60,
    )
    return out


def make_whoosh(workdir):
    out = workdir / "whoosh.wav"
    subprocess.run(
        [str(FFMPEG), "-y", "-f", "lavfi",
         "-i", "anoisesrc=color=pink:duration=0.6:amplitude=0.3",
         "-af", "afade=t=in:st=0:d=0.15,afade=t=out:st=0.3:d=0.3,volume=6dB,highpass=f=300,lowpass=f=3000",
         "-ac", "2", "-ar", "44100", str(out)],
        check=True, capture_output=True, timeout=60,
    )
    return out


def make_suspense(workdir):
    out = workdir / "suspense.wav"
    subprocess.run(
        [str(FFMPEG), "-y", "-f", "lavfi",
         "-i", "sine=frequency=80:duration=2.0",
         "-af", "afade=t=in:st=0:d=0.5,afade=t=out:st=1.5:d=0.5,volume=4dB,lowpass=f=200",
         "-ac", "2", "-ar", "44100", str(out)],
        check=True, capture_output=True, timeout=60,
    )
    return out


def make_tick(workdir):
    out = workdir / "tick.wav"
    subprocess.run(
        [str(FFMPEG), "-y", "-f", "lavfi",
         "-i", "sine=frequency=1200:duration=0.05",
         "-af", "afade=t=out:st=0.01:d=0.04,volume=5dB,highpass=f=800",
         "-ac", "2", "-ar", "44100", str(out)],
        check=True, capture_output=True, timeout=60,
    )
    return out


def gen_overlay_image(prompt, out_path, seed):
    if gen_image_cloudflare(prompt, out_path, width=720, height=720):
        return True
    tail = (
        ", bright vibrant colors, clean simple background, single clear subject centered, "
        "photorealistic, high detail, no text, no watermark"
    )
    url = (
        "https://image.pollinations.ai/prompt/"
        + urllib.parse.quote(prompt + tail)
        + f"?width=720&height=720&nologo=true&model=flux&seed={seed}&enhance=true"
    )
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=240)
            if r.ok and len(r.content) > 20000:
                tmp = out_path.with_suffix(".tmp")
                tmp.write_bytes(r.content)
                shutil.move(str(tmp), str(out_path))
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def build_caption_chunks(words, max_words=3):
    chunks = []
    cur = []
    for w in words:
        if cur:
            gap = w[1] - cur[-1][2]
            if len(cur) >= max_words or gap > 0.45:
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{FONT},{SIZE},&H0000FFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,1,0,1,6,2,2,60,60,{MV},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def fmt_ts(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(all_scene_words, path, w, h, roles=None):
    roles = roles or []
    mv = int(h * 0.30)
    out = ASS_HEADER.replace("{W}", str(w)).replace("{H}", str(h)).replace("{SIZE}", "92").replace("{FONT}", "Impact").replace("{MV}", str(mv))
    events = []
    for si, (scene_start, words) in enumerate(all_scene_words):
        is_hook = si == 0
        chunks = build_caption_chunks(words, 3)
        for ch in chunks:
            cs = scene_start + ch[0][1]
            ce = scene_start + ch[-1][2] + 0.12
            parts = []
            for i, (word, ws, we) in enumerate(ch):
                wtxt = word.upper() if is_hook else word
                kdur = max(int(round((we - ws) * 100)), 1)
                if i == 0:
                    parts.append("{\\k" + str(kdur) + "}" + wtxt)
                else:
                    prev_end = ch[i - 1][2]
                    lead = max(int(round((ws - prev_end) * 100)), 1)
                    parts.append("{\\k" + str(lead) + " }{\\k" + str(kdur) + "}" + wtxt)
            text = " ".join(parts).replace("\n", "\\N")
            pre = f"{{{chr(92)}fad(80,80)}}"
            if is_hook:
                pre = f"{{{chr(92)}fad(60,60){chr(92)}fs104{chr(92)}1c&H0000FF&}}"
            events.append(f"Dialogue: 0,{fmt_ts(cs)},{fmt_ts(ce)},Cap,,0,0,0,,{pre}{text}")
    path.write_text(out + "\n".join(events) + "\n", encoding="utf-8")


def probe_ok(path, w, h):
    r = subprocess.run(
        [str(FFPROBE), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        st = json.loads(r.stdout)["streams"][0]
        return st["width"] == w and st["height"] == h
    except Exception:
        return False


def audio_mean_volume(path):
    r = subprocess.run(
        [str(FFMPEG), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300,
    )
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", r.stderr)
    return float(m.group(1)) if m else None


def audio_level_ok(path):
    r = subprocess.run(
        [str(FFMPEG), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300,
    )
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", r.stderr)
    return m and float(m.group(1)) > -55


def video_qc(final, cfg, expect_min=15, expect_max=90):
    checks = {}
    checks["exists"] = final.exists() and final.stat().st_size > 200000
    d = media_dur(final)
    checks["duration_15_90s"] = expect_min <= d <= expect_max
    checks["resolution"] = probe_ok(final, cfg["video_width"], cfg["video_height"])
    r = subprocess.run(
        [str(FFPROBE), "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(final)],
        capture_output=True, text=True,
    )
    checks["has_audio"] = "audio" in r.stdout
    checks["audio_not_silent"] = bool(audio_level_ok(final))
    mv = audio_mean_volume(final)
    checks["audio_loud_enough"] = mv is not None and mv > -30
    failed = [k for k, ok in checks.items() if not ok]
    log("QC: " + ("PASS all" if not failed else "FAIL -> " + ", ".join(failed)))
    return not failed, {"duration": round(d, 1), "failed": failed}


def make_intro_hook_title_card(workdir, hook_text, dur=1.6, w=1080, h=1920):
    tf = workdir / "hookcard.txt"
    words = hook_text.upper().split()
    lines, cur = [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 <= 18:
            cur = (cur + " " + wd).strip()
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    tf.write_text("\n".join(lines[:4]), encoding="utf-8-sig")
    frames = int(dur * 30)
    vf = (
        f"color=c=0x101018:s={w}x{h}:d={dur},"
        f"drawtext=fontfile=arialbd.ttf:textfile={tf.name}:fontsize=110:fontcolor=white:"
        f"borderw=8:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:"
        f"alpha='min(1,max(0,(t-0.05)*6))'"
    )
    out = workdir / "intro.mp4"
    subprocess.run(
        [str(FFMPEG), "-y", "-f", "lavfi", "-i", f"color=c=0x101018:s={w}x{h}:d={dur}",
         "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", out.name],
        check=True, capture_output=True, timeout=300, cwd=str(workdir),
    )
    return out


def build_video(cfg, data, category="explained"):
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = BASE / "assets" / f"run_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    for fnt in ("arialbd.ttf", "impact.ttf"):
        src = pathlib.Path(r"C:\Windows\Fonts") / fnt if os.name == "nt" else BASE / "fonts" / fnt
        if os.name == "nt" and not src.exists():
            src = BASE / "fonts" / fnt
        if src.exists():
            shutil.copy(src, run_dir / fnt)

    w, h = cfg["video_width"], cfg["video_height"]
    voice, rate = cfg["voice"], cfg.get("voice_rate", "+0%")
    cat = CATEGORIES.get(category, CATEGORIES["explained"])
    scenes = data["scenes"]
    items = [
        {
            "text": data["hook"],
            "visuals": scenes[0].get("visuals") or ([scenes[0]["pexels_query"]] if scenes[0].get("pexels_query") else []),
            "overlays": scenes[0].get("overlays", []),
        }
    ] + [
        {
            "text": s["text"],
            "visuals": s.get("visuals") or ([s["pexels_query"]] if s.get("pexels_query") else []),
            "overlays": s.get("overlays", []),
        }
        for s in scenes[1:]
    ]
    n = len(items)
    total_words = sum(len(i["text"].split()) for i in items)

    log(f"TITLE: {data['title']}")
    log(f"NARRATION: {n} scenes, {total_words} words")

    def img_ok(path):
        if not path.exists() or path.stat().st_size < 15000:
            return False
        try:
            r = subprocess.run(
                [str(FFPROBE), "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, timeout=60,
            )
            wd, ht = r.stdout.strip().split(",")
            return int(wd) >= 500 and int(ht) >= 780
        except Exception:
            return False

    visuals = []
    topic = data.get("title", "")
    first_scene_img = None

    for i, it in enumerate(items):
        mains = []
        qs = it.get("visuals") or ["abstract bright psychology concept"]
        scene_txt = it.get("text", "")
        for j, q in enumerate(qs[:2]):
            src = None
            clip = run_dir / f"vid_{i:02d}_{j}.mp4"
            if cfg.get("pexels_api_key") and fetch_pexels_clip(q, clip, cfg["pexels_api_key"]):
                if media_dur(clip) >= 2:
                    src = clip
            if src is None:
                img = run_dir / f"img_{i:02d}_{j}.jpg"
                rich_q = enhance_prompt(q, scene_txt, topic)
                for attempt in range(3):
                    if gen_image_smart(rich_q, img, random.randint(1, 10 ** 6)) and verify_image(img):
                        src = img
                        break
                    img.unlink(missing_ok=True)
                if src is None:
                    raise RuntimeError(f"no visual scene {i} slot {j}: {q}")
            mains.append(src)
            log(f"[ASSET {i + 1}.{j + 1}/{n}] ok: {q}")
            if i == 0 and j == 0:
                first_scene_img = src
        ovs = []
        for j, q in enumerate(it.get("overlays", [])[:1]):
            ov_path = run_dir / f"ov_{i:02d}_{j}.jpg"
            log(f"[ASSET {i + 1}/{n}] overlay: {q}")
            rich_q = enhance_prompt(q, scene_txt, topic)
            ok = False
            for attempt in range(3):
                if gen_overlay_image(rich_q, ov_path, random.randint(1, 10 ** 6)) and ov_path.exists() and ov_path.stat().st_size > 15000:
                    ok = True
                    break
                ov_path.unlink(missing_ok=True)
            if ok:
                ovs.append(ov_path)
        visuals.append((mains, ovs))

    # LOOP ENDING: last scene uses first scene's image
    if n > 1 and first_scene_img:
        last_mains, last_ovs = visuals[-1]
        loop_img = run_dir / f"img_loop_{n-1:02d}_0.jpg"
        shutil.copy2(str(first_scene_img), str(loop_img))
        visuals[-1] = ([loop_img] + last_mains[1:], last_ovs)
        log(f"[LOOP] last scene uses first image: {first_scene_img.name}")

    all_scene_words = []
    parts = []
    t_cursor = 0.0
    n_items = len(items)
    boom = make_boom(run_dir)
    make_pop(run_dir)
    whoosh = make_whoosh(run_dir)
    suspense = make_suspense(run_dir)
    make_tick(run_dir)
    for i, it in enumerate(items):
        if i == 0:
            role, rate_i, pitch_i = "hook", "+18%", "+16Hz"
        elif i == n_items - 1:
            role, rate_i, pitch_i = "outro", "-2%", "+10Hz"
        else:
            role = "norm"
            rate_i = "+6%"
            pitch_i = ["+10Hz", "+14Hz", "+8Hz"][i % 3]
        log(f"[AUDIO {i + 1}/{n}] tts ({role})...")
        it["_role"] = role
        base = run_dir / f"seg_{i:02d}"
        if not tts_words(it["text"], base, voice, rate_i, pitch_i):
            raise RuntimeError(f"tts failed scene {i}")
        vox = process_voice(base.with_suffix(".mp3"), run_dir, i)
        seg_dur = media_dur(vox) + 0.28
        words = [tuple(w) for w in json.loads(base.with_suffix(".words.json").read_text(encoding="utf-8"))]
        all_scene_words.append((t_cursor, words))
        mains, ovs = visuals[i]
        log(f"[BUILD {i + 1}/{n}] imgs={len(mains)} +{len(ovs)}ov {seg_dur:.1f}s")
        part = scene_video_visual(
            mains, vox, seg_dur, i, run_dir, w, h,
            role=role,
            sfx=boom if i == 0 else None,
            overlays=ovs,
            whoosh=whoosh if i > 0 else None,
            suspense=suspense if i > 0 else None,
        )
        parts.append(part)
        t_cursor += seg_dur

    concat_file = run_dir / "list.txt"
    concat_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
    raw = run_dir / "raw.mp4"
    subprocess.run(
        [str(FFMPEG), "-y", "-f", "concat", "-safe", "0", "-i", concat_file.name, "-c", "copy", raw.name],
        check=True, capture_output=True, timeout=600, cwd=str(run_dir),
    )

    intro = make_intro_hook_title_card(run_dir, data["hook"]) if False else None
    ass = run_dir / "subs.ass"
    build_ass(all_scene_words, ass, w, h, roles=[it.get("_role", "norm") for it in items])
    final = BASE / "output" / f"short_{ts}.mp4"
    final.parent.mkdir(exist_ok=True)
    log("[SUBS] burning karaoke captions...")
    subprocess.run(
        [str(FFMPEG), "-y", "-i", raw.name, "-vf", f"ass={ass.name}:fontsdir=.", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy", "-movflags", "+faststart", str(final)],
        check=True, capture_output=True, timeout=1200, cwd=str(run_dir),
    )

    seo_tags = data.get("tags") or []
    hash_tags = [wd.strip("#").lower() for wd in data["description"].split() if wd.startswith("#")]
    all_tags = []
    for t in list(seo_tags) + hash_tags + ["psychology shorts", "human mind"]:
        tl = str(t).strip().lower()
        if tl and tl not in all_tags:
            all_tags.append(tl)
    meta = {
        "file": str(final),
        "title": data["title"],
        "description": data["description"],
        "tags": all_tags[:15],
    }
    (BASE / "output" / f"meta_{ts}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    append_json_list("used_topics.json", data["title"])
    append_json_list("used_scripts.json", " ".join([data["hook"]] + [s["text"] for s in scenes]))
    state_append({"ts": ts, "title": data["title"], "file": str(final)})
    log(f"DONE: {final}")
    return meta


def state_append(rec):
    p = BASE / "data_state.json"
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    rec["uploaded"] = False
    data.append(rec)
    json.dump(data[-300:], open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    cfg = load_config()
    if not cfg.get("gemini_api_key"):
        print("MISSING GEMINI KEY: paste into config.json")
        sys.exit(1)

    category_order = ["explained", "mystery", "whatif"]
    env_cat = os.environ.get("CATEGORY", "")
    if env_cat in category_order:
        chosen = env_cat
    else:
        today_cats = read_json_list("today_cats.json")

        if len(today_cats) >= 3:
            today_cats = []

        for cat in category_order:
            if cat not in today_cats:
                chosen = cat
                break
        else:
            chosen = category_order[0]

    log(f"=== STARTING CATEGORY: {CATEGORIES[chosen]['name']} ===")

    data = None
    qc_problems = []
    for attempt in range(1, 6):
        try:
            candidate = gemini_script(cfg["gemini_api_key"], cfg["niche"], chosen)
        except Exception as e:
            log(f"GEMINI retry {attempt}: {e}")
            time.sleep(5 * attempt)
            continue
        qc_problems = script_qc(candidate, cfg)
        if not qc_problems:
            data = candidate
            break
        log(f"SCRIPT QC fail (try {attempt}): {qc_problems}")
    if not data:
        log("SKIP RUN: no script passed QC after 5 tries")
        sys.exit(2)
    try:
        meta = build_video(cfg, data, chosen)
    except Exception as e:
        log(f"BUILD FAILED: {e}")
        sys.exit(3)
    ok, info = video_qc(pathlib.Path(meta["file"]), cfg)
    if not ok:
        log("UPLOAD BLOCKED BY QC")
        sys.exit(4)
    append_json_list("today_cats.json", chosen)
    if cfg.get("upload_to_youtube"):
        publish_at = None
        pub_hour = os.environ.get("PUBLISH_HOUR_UTC", "")
        now = datetime.datetime.now(datetime.timezone.utc)
        if pub_hour == "now":
            target = now + datetime.timedelta(minutes=3)
            publish_at = target.strftime("%Y-%m-%dT%H:%M:%SZ")
            log(f"PUBLISH NOW: {publish_at}")
        elif pub_hour.isdigit():
            target = now.replace(hour=int(pub_hour), minute=0, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            publish_at = target.strftime("%Y-%m-%dT%H:%M:%SZ")
            log(f"SCHEDULED PUBLISH: {publish_at}")
        try:
            from youtube_upload import upload_video
            vid = upload_video(meta, cfg.get("privacy", "public"), publish_at=publish_at)
            p = BASE / "data_state.json"
            st = json.loads(p.read_text(encoding="utf-8"))
            if st:
                st[-1]["uploaded"] = True
                st[-1]["youtube_id"] = vid
                json.dump(st, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception as e:
            log(f"UPLOAD FAILED (saved locally): {e}")
            sys.exit(5)

    ttk_key = os.environ.get("TTK_CLIENT_KEY", "")
    ttk_tk = os.environ.get("TTK_REFRESH_TOKEN", "")
    if cfg.get("upload_to_youtube") and ttk_key and ttk_tk:
        try:
            from tiktok_upload import post_video as ttk_post
            ttk_post(meta["file"], meta["title"])
        except Exception as e:
            log(f"TIKTOK FAILED: {e}")
    else:
        log("TIKTOK: not configured, skipped")


if __name__ == "__main__":
    main()
