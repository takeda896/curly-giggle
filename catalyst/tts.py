"""Narration: Kokoro TTS, one clip per sentence so captions can follow the voice."""
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "kokoro-v1.0.onnx"
VOICES = ROOT / "models" / "voices-v1.0.bin"
SR = 24000

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _two(n):
    if n < 20:
        return _ONES[n]
    t, o = divmod(n, 10)
    return _TENS[t] + ("-" + _ONES[o] if o else "")


def _year(m):
    y = int(m.group(0))
    hi, lo = divmod(y, 100)
    if 2000 <= y <= 2009:
        return "two thousand" + (" " + _ONES[lo] if lo else "")
    if lo == 0:
        return _two(hi) + " hundred"
    return _two(hi) + " " + ("oh " + _ONES[lo] if lo < 10 else _two(lo))


def speakable(text):
    """Text as it should be spoken. Captions keep the original text."""
    text = re.sub(r"(?<![\d,.])(19\d\d|20\d\d)(?![\d,])", _year, text)
    text = text.replace("D.C.", "D C").replace("xAI", "x A I")
    return text


def split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text.strip())
    return [p for p in parts if p]


class Narrator:
    def __init__(self, voice="af_heart", speed=1.0):
        from kokoro_onnx import Kokoro
        self.k = Kokoro(str(MODEL), str(VOICES))
        self.voice, self.speed = voice, speed
        self.lang = "en-gb" if voice.startswith("b") else "en-us"

    def sentence(self, text):
        audio, sr = self.k.create(speakable(text), voice=self.voice, speed=self.speed, lang=self.lang)
        assert sr == SR
        return _trim(np.asarray(audio, dtype=np.float32))


def _trim(a, thresh=0.008, pad=0.04):
    idx = np.flatnonzero(np.abs(a) > thresh)
    if idx.size == 0:
        return a
    p = int(pad * SR)
    return a[max(idx[0] - p, 0): idx[-1] + p]
