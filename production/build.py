#!/usr/bin/env python3
"""功能性訓練衛教 16:9 影片建置流程。

  python3 build.py tts    旁白（edge-tts 曉臻）→ build/tts/*.mp3 → timing.js
  python3 build.py mix    讀 build/cues.json（render.js cues 產生）→ 旁白＋音效＋背景音樂 → narration_mix.m4a
  python3 build.py mux    合併 build/seg_*.mp4 ＋ narration_mix.m4a → 成品 MP4

短版：前面加 VARIANT=short，改用 narration_short.json，輸出檔名都加上 _short（畫面在 build/short/）。

畫面由 render.js 以 Chrome 逐格擷取 functional_16x9.html。
"""
import hashlib, json, math, os, re, subprocess, sys, wave
import numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
ROOT = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(ROOT, "build")
TTS_DIR = os.path.join(BUILD, "tts")
SHORT = os.environ.get("VARIANT") == "short"
SFX = "_short" if SHORT else ""
SEGS = os.path.join(BUILD, "short") if SHORT else BUILD
OUT = os.path.join(ROOT, "功能性訓練_站起來才算數_16x9.mp4")
EDGE_TTS = os.environ.get("EDGE_TTS", os.path.expanduser("~/Library/Python/3.14/bin/edge-tts"))
VOICE, RATE = "zh-TW-HsiaoChenNeural", "+12%"
SR = 44100

# 字幕照原文顯示；唸的時候換成好發音的說法
SAY = [("1966", "一九六六"), ("「", ""), ("」", "")]


def read_audio(path):
    raw = subprocess.run([FF, "-loglevel", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def trim(a, thr=0.012, pad=0.04):
    idx = np.where(np.abs(a) > thr)[0]
    if not len(idx):
        return a
    s, e = max(0, idx[0] - int(pad * SR)), min(len(a), idx[-1] + int(pad * SR))
    return a[s:e]


def tts_clip(text):
    say = text
    for a, b in SAY:
        say = say.replace(a, b)
    key = hashlib.md5(f"{VOICE}|{RATE}|{say}".encode()).hexdigest()[:12]
    mp3 = os.path.join(TTS_DIR, key + ".mp3")
    if not os.path.exists(mp3) or os.path.getsize(mp3) == 0:
        for _ in range(3):
            r = subprocess.run([EDGE_TTS, "--voice", VOICE, f"--rate={RATE}", "--text", say, "--write-media", mp3],
                               capture_output=True, text=True)
            if r.returncode == 0 and os.path.getsize(mp3) > 0:
                break
        else:
            sys.exit(f"TTS 失敗：{say}\n{r.stderr[-400:]}")
    return mp3


def load_script():
    with open(os.path.join(ROOT, f"narration{SFX}.json"), encoding="utf-8") as f:
        return json.load(f)


PUNCT = "，、；：。？！"


def clause_marks(line, a):
    """依標點把一句切成子句，用語音中的停頓找出每個子句的起訖秒數（相對這句開頭）。"""
    clauses, cur = [], ""
    for ch in line:
        if ch in PUNCT:
            if cur: clauses.append(cur)
            cur = ""
        else:
            cur += ch
    if cur: clauses.append(cur)
    d = len(a) / SR
    if len(clauses) <= 1:
        return [[0.0, round(d, 3)]]
    n = int(.01 * SR)
    r = np.sqrt(np.convolve(a * a, np.ones(n) / n, mode="same"))
    quiet = r < .02 * r.max()
    gaps, i = [], 0
    while i < len(a):
        if quiet[i]:
            j = i
            while j < len(a) and quiet[j]: j += 1
            if (j - i) / SR >= .06 and i > 0 and j < len(a): gaps.append((i / SR, j / SR))
            i = j
        else:
            i += 1
    total = sum(len(c) for c in clauses)
    marks, used, prev = [], set(), 0.0
    for c in range(len(clauses) - 1):          # 每個子句邊界：找最接近按字數比例預估位置的停頓
        est = d * sum(len(x) for x in clauses[:c + 1]) / total
        cand = [(abs((g[0] + g[1]) / 2 - est), k) for k, g in enumerate(gaps) if k not in used and g[0] > prev]
        if cand and min(cand)[0] < .6:
            k = min(cand)[1]; used.add(k); g = gaps[k]
            marks.append([round(prev, 3), round(g[0], 3)]); prev = g[1]
        else:
            marks.append([round(prev, 3), round(est, 3)]); prev = est
    marks.append([round(prev, 3), round(d, 3)])
    return marks


def cmd_tts():
    os.makedirs(TTS_DIR, exist_ok=True)
    scenes = load_script()
    timing, subs, clips = [], [], []
    t = 0.0
    for si, sc in enumerate(scenes):
        beats, durs, marks = [], [], []
        lt = sc.get("lead", 0.4 if si == 0 else (0.35 if SHORT else 0.45))
        for li, line in enumerate(sc["lines"]):
            a = trim(read_audio(tts_clip(line)))
            d = len(a) / SR
            beats.append(round(lt, 3)); durs.append(round(d, 3)); marks.append(clause_marks(line, a))
            clips.append({"at": round(t + lt, 3), "file": tts_clip(line)})
            subs.append({"a": round(t + lt - 0.05, 3), "b": round(t + lt + d + 0.12, 3), "text": line})
            gap = 0.18 if line[-1] in "，；、：" else 0.34
            lt += d + gap
        end = t + lt + (0.3 if SHORT else 0.4) + sc.get("tail", 0)
        timing.append({"id": sc["id"], "start": round(t, 3), "end": round(end, 3), "beats": beats, "durs": durs,
                       "lines": sc["lines"], "marks": marks})
        print(f"{sc['id']:5s} {t:7.2f} → {end:7.2f}  ({end - t:5.2f}s, {len(beats)} 句)")
        t = end
    with open(os.path.join(ROOT, f"timing{SFX}.js"), "w", encoding="utf-8") as f:
        f.write("window.TIMING = " + json.dumps(timing, ensure_ascii=False) + ";\n")
        f.write("window.SUBS = " + json.dumps(subs, ensure_ascii=False) + ";\n")
    with open(os.path.join(BUILD, f"clips{SFX}.json"), "w", encoding="utf-8") as f:
        json.dump(clips, f, ensure_ascii=False)
    print(f"總長 {t:.1f}s（{int(t // 60)} 分 {t % 60:.0f} 秒）")


# ───────────────────────── 音效 ─────────────────────────
def env(n, attack=0.005, decay=0.1):
    t = np.arange(n) / SR
    return np.minimum(1, t / attack) * np.exp(-t / decay)


def sfx_bank():
    rng = np.random.default_rng(11)
    B = {}
    n = int(0.5 * SR); noise = rng.standard_normal(n)
    out = np.zeros(n); y = 0.0
    for i in range(n):
        a = 0.02 + 0.2 * math.sin(math.pi * i / n)
        y += a * (noise[i] - y); out[i] = y
    B["whoosh"] = out * np.sin(np.linspace(0, math.pi, n)) ** 1.5 * 1.1
    n = int(0.09 * SR); t = np.arange(n) / SR
    B["pop"] = np.sin(2 * math.pi * (520 * t + 3600 * t * t)) * env(n, 0.002, 0.03) * 0.42
    n = int(0.05 * SR); t = np.arange(n) / SR
    B["tick"] = np.sin(2 * math.pi * 1800 * t) * env(n, 0.001, 0.012) * 0.3
    n = int(1.0 * SR); t = np.arange(n) / SR
    B["ding"] = (np.sin(2 * math.pi * 1046.5 * t) * 0.5 + np.sin(2 * math.pi * 1568 * t) * 0.3 +
                 np.sin(2 * math.pi * 2093 * t) * 0.12) * env(n, 0.002, 0.3) * 0.3
    n = int(0.28 * SR); t = np.arange(n) / SR
    B["stamp"] = (np.sin(2 * math.pi * (130 - 170 * t) * t) * env(n, 0.001, 0.07) +
                  rng.standard_normal(n) * env(n, 0.0005, 0.015) * 0.35) * 0.7
    n = int(0.7 * SR); t = np.arange(n) / SR
    clicks = np.zeros(n)
    for k in range(10):
        s = int(k * 0.06 * SR); m = int(0.012 * SR)
        clicks[s:s + m] += np.sin(2 * math.pi * 2400 * np.arange(m) / SR) * env(m, 0.0005, 0.004)
    B["count"] = clicks * 0.22
    n = int(0.45 * SR); t = np.arange(n) / SR
    B["wrong"] = (np.sin(2 * math.pi * 330 * t) * (t < 0.18) + np.sin(2 * math.pi * 262 * t) * (t >= 0.18)) \
        * env(n, 0.004, 0.25) * 0.3
    return B


def make_bgm(total):
    """溫和的 C–G–Am–F 循環，82 BPM，柔和鋪底＋鋼琴感琶音。"""
    bpm = 82; beat = 60 / bpm; bar = beat * 4
    chords = [[48, 60, 64, 67], [43, 59, 62, 67], [45, 60, 64, 69], [41, 57, 60, 65]]
    hz = lambda m: 440 * 2 ** ((m - 69) / 12)
    loop = np.zeros(int(bar * 4 * SR))
    for b, ch in enumerate(chords):
        s0 = int(b * bar * SR); n = int(bar * SR); t = np.arange(n) / SR
        pad = sum(np.sin(2 * math.pi * hz(m) * t) * (0.6 if m < 50 else 1) for m in ch) / len(ch)
        loop[s0:s0 + n] += pad * np.minimum(1, t / 0.6) * np.minimum(1, (bar - t) / 0.5) * 0.16
        for k, idx in enumerate([1, 2, 3, 2, 1, 2, 3, 2]):
            m = ch[idx] + 12
            p0 = s0 + int(k * beat / 2 * SR); pn = int(0.6 * SR); pt = np.arange(pn) / SR
            note = (np.sin(2 * math.pi * hz(m) * pt) + 0.25 * np.sin(4 * math.pi * hz(m) * pt)) * env(pn, 0.004, 0.22)
            seg = loop[p0:p0 + pn]
            seg += note[:len(seg)] * (0.09 if k % 2 == 0 else 0.06)
    reps = int(math.ceil(total * SR / len(loop)))
    bgm = np.tile(loop, reps)[:int(total * SR)]
    fi, fo = int(1.0 * SR), int(2.5 * SR)
    bgm[:fi] *= np.linspace(0, 1, fi)
    bgm[-fo:] *= np.linspace(1, 0, fo)
    return bgm


def place(buf, clip, at, gain=1.0):
    s = int(at * SR)
    if s >= len(buf) or s < 0:
        return
    e = min(len(buf), s + len(clip))
    buf[s:e] += clip[:e - s] * gain


def cmd_mix():
    timing_js = open(os.path.join(ROOT, f"timing{SFX}.js"), encoding="utf-8").read()
    timing = json.loads(re.search(r"window.TIMING = (.*?);\n", timing_js).group(1))
    total = timing[-1]["end"]
    clips = json.load(open(os.path.join(BUILD, f"clips{SFX}.json"), encoding="utf-8"))
    cues = json.load(open(os.path.join(BUILD, f"cues{SFX}.json"), encoding="utf-8"))
    n = int((total + 0.5) * SR)
    voice, sfx = np.zeros(n), np.zeros(n)
    for c in clips:
        place(voice, trim(read_audio(c["file"])), c["at"])
    B = sfx_bank()
    gains = {"whoosh": 0.55, "pop": 0.8, "tick": 0.8, "ding": 0.75, "stamp": 0.9, "count": 0.8, "wrong": 0.8}
    for c in cues:
        place(sfx, B[c["type"]], c["t"], gains.get(c["type"], 0.8))
    bgm = make_bgm(n / SR)
    k = int(0.2 * SR)
    venv = np.convolve(np.abs(voice), np.ones(k) / k, mode="same")
    venv = np.clip(venv / (venv.max() + 1e-9) * 7, 0, 1)
    mix = voice * 1.0 + sfx * 0.6 + bgm * (0.5 - 0.3 * venv)
    mix /= max(1.0, np.abs(mix).max() / 0.93)
    wav = os.path.join(BUILD, f"mix{SFX}.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", wav, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", str(SR),
                    "-c:a", "aac", "-b:a", "192k",
                    os.path.join(ROOT, f"narration_mix{SFX}.m4a")], check=True)
    print(f"narration_mix{SFX}.m4a", f"{n / SR:.1f}s")


def cmd_mux():
    segs = sorted(f for f in os.listdir(SEGS) if re.match(r"seg_\d+\.mp4$", f))
    lst = os.path.join(SEGS, "segs.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.join(SEGS, s)}'\n" for s in segs)
    video = os.path.join(SEGS, "video.mp4")
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", video], check=True)
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", video, "-i", os.path.join(ROOT, f"narration_mix{SFX}.m4a"),
                    "-c:v", "copy", "-c:a", "copy", "-shortest", "-movflags", "+faststart", OUT], check=True)
    print("done:", OUT)


if __name__ == "__main__":
    {"tts": cmd_tts, "mix": cmd_mix, "mux": cmd_mux}[sys.argv[1]]()
