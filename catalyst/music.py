"""Royalty-free background bed, synthesized: slow minor pad + soft pulse + swells on chapter cards."""
import numpy as np

SR = 48000
# A minor - F - C - G, voiced low and wide
CHORDS = [[45, 52, 57, 60, 64], [41, 48, 53, 57, 60], [48, 52, 55, 60, 64], [43, 50, 55, 59, 62]]


def _hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _lp(x, cutoff):
    """One-pole low-pass (scipy if present, moving average otherwise)."""
    try:
        from scipy.signal import lfilter
    except ImportError:
        k = max(int(SR / cutoff / 2), 1)
        return np.convolve(x, np.ones(k) / k, mode="same")
    a = np.exp(-2 * np.pi * cutoff / SR)
    return lfilter([1 - a], [1, -a], x)


def bed(seconds, swells=(), seed=7):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    chord_len = 8.0
    for ci in range(int(seconds // chord_len) + 2):
        start = ci * chord_len
        notes = CHORDS[ci % len(CHORDS)]
        s0, s1 = int(max(start - 1.5, 0) * SR), int(min(start + chord_len + 1.5, seconds) * SR)
        if s0 >= n:
            break
        tt = t[s0:s1] - (start - 1.5)
        env = np.clip(tt / 2.5, 0, 1) * np.clip((chord_len + 3.0 - tt) / 2.5, 0, 1)
        seg = np.zeros(s1 - s0)
        for m in notes:
            f = _hz(m)
            for det in (-0.12, 0.12):
                ph = rng.uniform(0, 2 * np.pi)
                seg += np.sin(2 * np.pi * f * (1 + det / 100) * t[s0:s1] + ph) * 0.5
                seg += 0.18 * np.sin(2 * np.pi * 2 * f * t[s0:s1] + ph)
        out[s0:s1] += seg * env / len(notes)
    # soft sub pulse, one per beat at 70 bpm
    beat = 60 / 70
    ph = (t % beat) / beat
    root = np.array([_hz(CHORDS[int(x // chord_len) % 4][0] - 12) for x in t[:: SR // 10]])
    root = np.repeat(root, SR // 10)[:n]
    out += 0.22 * np.sin(2 * np.pi * root * t) * np.exp(-ph * 5)
    # airy noise
    out += 0.02 * _lp(rng.standard_normal(n), 2500)
    for s in swells:
        a, b = int(max(s - 1.4, 0) * SR), int(min(s + 0.4, seconds) * SR)
        if a >= b:
            continue
        k = np.linspace(0, 1, b - a)
        env = np.where(k < 0.78, (k / 0.78) ** 2, (1 - k) / 0.22)
        out[a:b] += 0.35 * _lp(rng.standard_normal(b - a), 1800) * env
    out = _lp(out, 3200)
    fade = int(3 * SR)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    return (out / (np.max(np.abs(out)) + 1e-9)).astype(np.float32)
