"""TTS engines. Default: Kokoro-82M (Apache-2.0, commercial use allowed) via kokoro-onnx, running
locally on CPU. Any engine only has to turn one sentence into mono float32 audio."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import numpy as np

MODEL_DIR = Path(os.environ.get("SLEEP_VOICE_MODELS", "~/.sleep_voice/models")).expanduser()
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")

# Male English voices in Kokoro v1.0 (am_ = American, bm_ = British), with notes for sleep use.
MALE_VOICES = {
    "am_michael": "American, warm and steady; the safest sleep narrator",
    "am_onyx": "American, deep and dark",
    "am_adam": "American, neutral",
    "am_eric": "American, lighter",
    "am_liam": "American, young and soft",
    "am_echo": "American, airy",
    "am_fenrir": "American, strong and rough",
    "am_puck": "American, lively (not ideal for sleep)",
    "bm_george": "British, mature and calm; classic documentary",
    "bm_lewis": "British, deep and slow",
    "bm_daniel": "British, soft",
    "bm_fable": "British, storyteller",
}


class Engine(Protocol):
    sample_rate: int
    engine_id: str

    def synthesize(self, text: str, speed: float) -> np.ndarray: ...


def parse_voice(spec: str) -> list[tuple[str, float]]:
    """'am_michael' or 'am_michael:0.6,bm_george:0.4' -> normalised weights."""
    parts = []
    for item in spec.split(","):
        name, _, w = item.strip().partition(":")
        parts.append((name.strip(), float(w) if w else 1.0))
    total = sum(w for _, w in parts)
    if total <= 0:
        raise ValueError("voice weights must sum to > 0")
    return [(n, w / total) for n, w in parts]


def ensure_models(model_dir: Path = MODEL_DIR) -> tuple[Path, Path]:
    model_dir.mkdir(parents=True, exist_ok=True)
    paths = [model_dir / f for f in MODEL_FILES]
    missing = [p for p in paths if not p.exists()]
    if missing:
        import urllib.request

        for p in missing:
            print(f"Downloading {p.name} (one time, ~{'310' if p.suffix == '.onnx' else '27'} MB)...")
            tmp = p.with_suffix(p.suffix + ".part")
            urllib.request.urlretrieve(MODEL_URL + p.name, tmp)
            tmp.rename(p)
    return paths[0], paths[1]


class KokoroEngine:
    def __init__(self, voice: str = "am_michael", lang: str | None = None, model_dir: Path = MODEL_DIR):
        from kokoro_onnx import Kokoro

        model, voices = ensure_models(model_dir)
        self._k = Kokoro(str(model), str(voices))
        available = set(self._k.get_voices())
        mix = parse_voice(voice)
        unknown = [n for n, _ in mix if n not in available]
        if unknown:
            raise ValueError(f"unknown voice(s) {unknown}; male options: {', '.join(MALE_VOICES)}")
        # A blend is a weighted average of style vectors: a new, stable timbre of your own.
        self.style = sum(w * self._k.get_voice_style(n) for n, w in mix).astype(np.float32)
        self.lang = lang or ("en-gb" if mix[0][0].startswith("b") else "en-us")
        self.voice = voice
        self.sample_rate = 24_000
        self.engine_id = f"kokoro-v1.0|{voice}|{self.lang}"

    def synthesize(self, text: str, speed: float) -> np.ndarray:
        audio, sr = self._k.create(text, voice=self.style, speed=speed, lang=self.lang, trim=True)
        self.sample_rate = sr
        return np.asarray(audio, dtype=np.float32)
