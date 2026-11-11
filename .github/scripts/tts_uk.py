"""Ukrainian narration on GitHub Actions (the open internet is there): Piper's ukrainian_tts voice, one WAV per line,
then an intelligibility check that transcribes each WAV with Whisper and compares it with the text.

    python .github/scripts/tts_uk.py tg_content/videos/<slug>/voice.json out/<slug>

voice.json: {"speaker": "mykyta" | "lada" | "tetiana", "length_scale": 1.0, "lines": [{"id": "b01", "text": "..."}]}
Write numbers as words: the voice reads digits poorly.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
import wave
from pathlib import Path

VOICE = "uk_UA-ukrainian_tts-medium"
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/uk/uk_UA/ukrainian_tts/medium/"


def fetch(name: str, dest: Path) -> Path:
    path = dest / name
    if not path.exists():
        dest.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(BASE + name, path)
    return path


def words(text: str) -> list[str]:
    return re.findall(r"[a-zа-яіїєґ0-9']+", text.lower().replace("ʼ", "'").replace("’", "'"))


def wer(ref: list[str], hyp: list[str]) -> float:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[len(hyp)] / max(len(ref), 1)


def main(script: str, out_dir: str) -> int:
    cfg = json.loads(Path(script).read_text(encoding="utf-8"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    models = Path("voices")
    model = fetch(f"{VOICE}.onnx", models)
    meta = json.loads(fetch(f"{VOICE}.onnx.json", models).read_text(encoding="utf-8"))
    speakers = meta.get("speaker_id_map") or {}
    sid = speakers.get(cfg.get("speaker", "mykyta"), 0)
    ls = float(cfg.get("length_scale", 1.0))
    print(f"voice {VOICE}, speakers {speakers}, using {cfg.get('speaker')} = {sid}, length_scale {ls}")

    from piper import PiperVoice
    voice = PiperVoice.load(str(model))
    try:
        from piper import SynthesisConfig
        syn = SynthesisConfig(speaker_id=sid, length_scale=ls)

        def synth(text: str, wf: wave.Wave_write) -> None:
            voice.synthesize_wav(text, wf, syn_config=syn)
    except ImportError:                       # piper-tts 1.2
        def synth(text: str, wf: wave.Wave_write) -> None:
            voice.synthesize(text, wf, speaker_id=sid, length_scale=ls)

    report = []
    for line in cfg["lines"]:
        path = out / f"{line['id']}.wav"
        with wave.open(str(path), "wb") as wf:
            synth(line["text"], wf)
        with wave.open(str(path), "rb") as wf:
            dur = wf.getnframes() / wf.getframerate()
        report.append({"id": line["id"], "text": line["text"], "seconds": round(dur, 2)})

    try:
        from faster_whisper import WhisperModel
        asr = WhisperModel("small", device="cpu", compute_type="int8")
        for r in report:
            segs, _ = asr.transcribe(str(out / f"{r['id']}.wav"), language="uk", beam_size=5)
            heard = " ".join(s.text.strip() for s in segs)
            r["heard"] = heard
            r["wer"] = round(wer(words(r["text"]), words(heard)), 3)
    except Exception as e:                     # the check is a help, not a requirement
        print(f"whisper check skipped: {type(e).__name__}: {e}")

    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in report:
        print(f"{r['id']}  {r['seconds']:5.2f}s  wer={r.get('wer')}  heard: {r.get('heard', '')[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
