"""TTS engines. Each turns a sentence or paragraph into mono float32 audio at 24 kHz.

  kokoro      local, CPU, free          Kokoro-82M (Apache-2.0)
  chatterbox  local, GPU advised, free  Chatterbox (MIT) - most natural open model; optional voice cloning
  openai      cloud, ~$0.015/min        gpt-4o-mini-tts - style steered by plain-English instructions
  elevenlabs  cloud, ~$0.10-0.20/min    the benchmark for natural narration

All of them allow commercial use of the output (check your plan's terms for the cloud ones).
"""

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
    # "paragraph" engines keep natural intonation across sentences; the renderer sends whole paragraphs.
    preferred_unit: str

    def synthesize(self, text: str, speed: float, sentence_pause: float = 0.0) -> np.ndarray: ...


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
        self.preferred_unit = "paragraph"

    def synthesize(self, text: str, speed: float, sentence_pause: float = 0.0) -> np.ndarray:
        audio, sr = self._k.create(text, voice=self.style, speed=speed, lang=self.lang, trim=True,
                                   sentence_pause=sentence_pause, clause_pause=min(0.18, sentence_pause / 4))
        self.sample_rate = sr
        return np.asarray(audio, dtype=np.float32)


# ---------------------------------------------------------------- cloud engines
SLEEP_INSTRUCTIONS = (
    "You are narrating a calm documentary meant to help the listener fall asleep. Speak slowly and softly, "
    "in a warm, low, relaxed male voice, close to the microphone. Keep an even, gentle pace with natural "
    "pauses at commas and full stops. No excitement, no emphasis spikes, no rising energy. Sound like a "
    "thoughtful person reading aloud late at night, not like an announcer."
)


def _pcm16_to_float(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def _post_with_retry(client, url: str, *, headers: dict, json: dict, params: dict | None = None,
                     attempts: int = 4):
    import time

    for i in range(attempts):
        r = client.post(url, headers=headers, json=json, params=params)
        if r.status_code == 200:
            return r.content
        if r.status_code in (429, 500, 502, 503, 504) and i < attempts - 1:
            time.sleep(2 ** (i + 1))
            continue
        raise RuntimeError(f"TTS request failed: HTTP {r.status_code}: {r.text[:300]}")


class OpenAIEngine:
    """gpt-4o-mini-tts. Pace and mood come from `instructions` (plain English); the speed factor is
    mapped into the instructions because this model is steered by text, not a speed knob."""

    def __init__(self, voice: str = "onyx", model: str = "gpt-4o-mini-tts", instructions: str = SLEEP_INSTRUCTIONS,
                 api_key: str | None = None, http=None):
        import httpx

        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("Set OPENAI_API_KEY to use the openai engine.")
        self.voice, self.model, self.instructions = voice, model, instructions
        self.http = http or httpx.Client(timeout=120)
        self.sample_rate = 24_000
        import hashlib

        self.engine_id = f"openai|{model}|{voice}|{hashlib.sha1(instructions.encode()).hexdigest()[:10]}"
        self.preferred_unit = "paragraph"

    def synthesize(self, text: str, speed: float, sentence_pause: float = 0.0) -> np.ndarray:
        pace = "very slowly" if speed <= 0.82 else "slowly" if speed <= 0.92 else "at a relaxed pace"
        data = _post_with_retry(
            self.http, "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "voice": self.voice, "input": text, "response_format": "pcm",
                  "instructions": f"{self.instructions} Speak {pace}."},
        )
        return _pcm16_to_float(data)


class ElevenLabsEngine:
    """ElevenLabs. Uses previous/next text so intonation flows across paragraph boundaries."""

    def __init__(self, voice_id: str, model: str = "eleven_multilingual_v2", stability: float = 0.75,
                 similarity: float = 0.8, style: float = 0.0, api_key: str | None = None, http=None):
        import httpx

        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise RuntimeError("Set ELEVENLABS_API_KEY to use the elevenlabs engine.")
        self.voice_id, self.model = voice_id, model
        self.settings = {"stability": stability, "similarity_boost": similarity, "style": style,
                         "use_speaker_boost": False}
        self.http = http or httpx.Client(timeout=180)
        self.sample_rate = 24_000
        self.engine_id = f"elevenlabs|{model}|{voice_id}|{stability}|{similarity}|{style}"
        self.preferred_unit = "paragraph"
        self.context: tuple[str, str] = ("", "")  # set by the renderer: (previous_text, next_text)

    def synthesize(self, text: str, speed: float, sentence_pause: float = 0.0) -> np.ndarray:
        prev, nxt = self.context
        data = _post_with_retry(
            self.http, f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}",
            headers={"xi-api-key": self.api_key},
            params={"output_format": "pcm_24000"},
            json={"text": text, "model_id": self.model, "previous_text": prev[-600:] or None,
                  "next_text": nxt[:600] or None,
                  "voice_settings": {**self.settings, "speed": max(0.7, min(1.2, speed))}},
        )
        return _pcm16_to_float(data)


# ---------------------------------------------------------------- local neural engine
class ChatterboxEngine:
    """Chatterbox (Resemble AI, MIT). Very natural; runs best on an NVIDIA GPU or Apple Silicon.
    `reference` = a clean 10-30 s WAV of a calm male voice to clone (only use a voice you have the
    rights to, e.g. your own). Low exaggeration + low cfg_weight = calm, slower delivery."""

    def __init__(self, reference: str | None = None, exaggeration: float = 0.3, cfg_weight: float = 0.35,
                 device: str | None = None):
        try:
            import torch
            from chatterbox.tts import ChatterboxTTS
        except ImportError as exc:
            raise RuntimeError("Install Chatterbox first: pip install chatterbox-tts") from exc
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = ChatterboxTTS.from_pretrained(device=device)
        self.reference, self.exaggeration, self.cfg_weight = reference, exaggeration, cfg_weight
        self.sample_rate = int(self.model.sr)
        ref_tag = Path(reference).name if reference else "default"
        self.engine_id = f"chatterbox|{ref_tag}|{exaggeration}|{cfg_weight}"
        self.preferred_unit = "paragraph"

    def synthesize(self, text: str, speed: float, sentence_pause: float = 0.0) -> np.ndarray:
        wav = self.model.generate(text, audio_prompt_path=self.reference, exaggeration=self.exaggeration,
                                  cfg_weight=self.cfg_weight)
        return wav.squeeze().detach().cpu().numpy().astype(np.float32)


def make_engine(name: str, voice: str | None = None, **opts) -> Engine:
    name = name.lower()
    if name == "kokoro":
        return KokoroEngine(voice or "am_michael")
    if name == "openai":
        return OpenAIEngine(voice or "onyx", **opts)
    if name == "elevenlabs":
        if not voice:
            raise ValueError("--voice must be an ElevenLabs voice_id for the elevenlabs engine")
        return ElevenLabsEngine(voice, **opts)
    if name == "chatterbox":
        return ChatterboxEngine(reference=voice, **opts)
    raise ValueError(f"unknown engine {name!r}: kokoro | chatterbox | openai | elevenlabs")
