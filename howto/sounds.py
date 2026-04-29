"""Tiny in-process tone generator for UI sound effects.

Synthesizes short beeps as 16-bit mono WAV on first use and caches them
under ``resources/sounds/``. QSoundEffect replays them without re-decoding,
so latency on subsequent plays is sub-millisecond.
"""

import math
import struct
import wave
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QSoundEffect

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOUNDS_DIR = PROJECT_ROOT / 'resources' / 'sounds'


def _generate_beep(path, freq=880, duration_ms=120, sample_rate=44100, volume=0.5):
    n = int(sample_rate * duration_ms / 1000)
    fade = max(1, int(sample_rate * 0.01))  # 10ms fade in/out — click-free
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        for i in range(n):
            env = 1.0
            if i < fade:
                env = i / fade
            elif i > n - fade:
                env = (n - i) / fade
            s = int(volume * env * 32767 * math.sin(2 * math.pi * freq * i / sample_rate))
            w.writeframes(struct.pack('<h', s))


_TONES = {
    # name: (freq_hz, duration_ms)
    'tick': (880, 100),
    'go':   (1320, 240),
}

_effects = {}


def _ensure_effect(name):
    eff = _effects.get(name)
    if eff is not None:
        return eff
    if name not in _TONES:
        return None
    freq, dur = _TONES[name]
    path = SOUNDS_DIR / f'{name}.wav'
    if not path.exists():
        _generate_beep(path, freq=freq, duration_ms=dur)
    eff = QSoundEffect()
    eff.setSource(QUrl.fromLocalFile(str(path)))
    eff.setVolume(0.6)
    _effects[name] = eff
    return eff


def play(name):
    eff = _ensure_effect(name)
    if eff is not None:
        eff.play()
