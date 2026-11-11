"""ElevenLabs voice-over on GitHub Actions, careful with credits.

    python .github/scripts/tts_eleven.py samples tg_content/videos/<slug>/voice.json out/samples --max-chars 300
    python .github/scripts/tts_eleven.py render  tg_content/videos/<slug>/voice.json out/<slug> --cache cache --max-chars 1500

samples: finds the most used native Ukrainian voices in the ElevenLabs voice library, adds the best few to the
         account, and reads one short line with each (`sample_text` in voice.json, else the first line). Free voice
         previews are saved too. Costs about len(text) credits per voice.
render:  reads every line with `voice_id` / `model` / `voice_settings` from voice.json. A line whose text, voice and
         settings did not change since the last run is reused from --cache (no credits). Before spending, the total is
         checked against --max-chars and nothing is generated if it is over.
Both log the account's remaining credits before and after (needs the key's User read permission; skipped without it)
and check every file with Whisper (word error rate against the text).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

API = "https://api.elevenlabs.io"
DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_SETTINGS = {"stability": 0.45, "similarity_boost": 0.8, "style": 0.25, "use_speaker_boost": True}


def client() -> httpx.Client:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        sys.exit("ELEVENLABS_API_KEY is not set")
    return httpx.Client(base_url=API, headers={"xi-api-key": key}, timeout=120)


def credits(http: httpx.Client) -> str:
    try:
        r = http.get("/v1/user/subscription")
        r.raise_for_status()
        d = r.json()
        return f"{d.get('character_limit', 0) - d.get('character_count', 0)} credits left of {d.get('character_limit')}"
    except Exception as e:                      # the key may not have User read
        return f"credits unknown ({type(e).__name__})"


def spoken(line: dict) -> str:
    return (line.get("say") or line["text"]).strip()


def tts(http: httpx.Client, voice_id: str, text: str, model: str, settings: dict, out: Path,
        prev: str = "", nxt: str = "") -> None:
    body = {"text": text, "model_id": model, "voice_settings": settings}
    if prev:
        body["previous_text"] = prev[-300:]
    if nxt:
        body["next_text"] = nxt[:300]
    r = http.post(f"/v1/text-to-speech/{voice_id}", params={"output_format": "mp3_44100_128"}, json=body)
    if r.status_code >= 400:
        sys.exit(f"text-to-speech {r.status_code}: {r.text[:300]}")
    out.write_bytes(r.content)


def words(text: str) -> list[str]:
    return re.findall(r"[a-zа-яіїєґ0-9']+", text.lower().replace("ʼ", "'").replace("’", "'"))


def wer(ref: list[str], hyp: list[str]) -> float:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[len(hyp)] / max(len(ref), 1)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return round(float(out or 0), 2)


def pcm16k(path: Path):
    """The audio as 16 kHz mono float32 via ffmpeg (faster-whisper's own decoder breaks on new PyAV)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def check(items: list[dict], folder: Path) -> None:
    """Whisper hears each file; a failure here never loses the audio already paid for."""
    try:
        from faster_whisper import WhisperModel
        asr = WhisperModel("small", device="cpu", compute_type="int8")
    except Exception as e:
        print(f"whisper check skipped: {type(e).__name__}: {e}")
        return
    for it in items:
        try:
            segs, _ = asr.transcribe(pcm16k(folder / it["file"]), language="uk", beam_size=5)
            it["heard"] = " ".join(s.text.strip() for s in segs)
            if it.get("text"):
                it["wer"] = round(wer(words(it["text"]), words(it["heard"])), 3)
        except Exception as e:
            print(f"whisper on {it['file']}: {type(e).__name__}: {e}")


# ---------------------------------------------------------------- samples
def variants(cfg: dict, out: Path, max_chars: int) -> None:
    """One voice, several models / settings, one short line each: compare by ear before a whole video."""
    http = client()
    print("before:", credits(http))
    text = (cfg.get("sample_text") or spoken(cfg["lines"][0])).strip()
    tries = cfg["sample_variants"]
    need = sum(len((v.get("text") or text).strip()) for v in tries)    # a variant may bring its own line
    if need > max_chars:
        sys.exit(f"{need} characters for {len(tries)} variants, more than --max-chars {max_chars}")
    out.mkdir(parents=True, exist_ok=True)
    result = []
    for i, v in enumerate(tries, 1):
        f = f"variant_{i}.mp3"
        model, settings = v.get("model", DEFAULT_MODEL), v.get("voice_settings", DEFAULT_SETTINGS)
        line = (v.get("text") or text).strip()
        body = {"text": line, "model_id": model, "voice_settings": settings}
        r = http.post(f"/v1/text-to-speech/{cfg['voice_id']}", params={"output_format": "mp3_44100_128"}, json=body)
        if r.status_code >= 400:                  # an unknown model costs nothing: note it and go on
            print(f"{i}. {v.get('label', model)}: {r.status_code} {r.text[:200]}")
            continue
        (out / f).write_bytes(r.content)
        result.append({"n": i, "file": f, "label": v.get("label", model), "model": model, "voice_settings": settings,
                       "text": line, "seconds": duration(out / f)})
        (out / "samples.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    check(result, out)
    (out / "samples.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for s_ in result:
        print(f"{s_['n']}. {s_['label']} {s_['seconds']}s wer={s_.get('wer')} | {s_.get('heard', '')}")
    print("after:", credits(http))


def samples(cfg: dict, out: Path, max_chars: int) -> None:
    if cfg.get("sample_variants"):
        return variants(cfg, out, max_chars)
    http = client()
    print("before:", credits(http))
    try:
        models = http.get("/v1/models").json()
        uk = [m["model_id"] for m in models if any(l.get("language_id") == "uk" for l in m.get("languages") or [])]
        print("models that speak Ukrainian:", uk)
    except Exception as e:
        print(f"models unknown: {type(e).__name__}")
    r = http.get("/v1/shared-voices", params={"page_size": 40, "language": "uk", "sort": "usage_character_count_1y"})
    r.raise_for_status()
    found = [v for v in r.json().get("voices", []) if (v.get("language") or "").startswith("uk")]
    found.sort(key=lambda v: (v.get("usage_character_count_1y") or 0), reverse=True)
    for v in found[:12]:
        print(f"  {v.get('name')!r:32} {v.get('gender')} {v.get('age')} usage1y={v.get('usage_character_count_1y')} "
              f"cloned={v.get('cloned_by_count')} {(v.get('description') or '')[:60]!r}")
    out.mkdir(parents=True, exist_ok=True)
    listing = [{"name": v.get("name"), "gender": v.get("gender"), "age": v.get("age"), "voice_id": v.get("voice_id"),
                "public_owner_id": v.get("public_owner_id"), "usage_1y": v.get("usage_character_count_1y"),
                "cloned": v.get("cloned_by_count"), "description": v.get("description"),
                "preview_url": v.get("preview_url")} for v in found[:12]]
    (out / "voices.json").write_text(json.dumps(listing, ensure_ascii=False, indent=1), encoding="utf-8")
    if not cfg.get("sample_tts"):
        previews = []
        for i, v in enumerate(listing[: int(cfg.get("samples", 6))], 1):
            if not v["preview_url"]:
                continue
            f = f"preview_{i}.mp3"
            try:
                (out / f).write_bytes(httpx.get(v["preview_url"], timeout=60).content)
            except Exception as e:
                print(f"preview {v['name']}: {type(e).__name__}")
                continue
            previews.append({"n": i, "file": f, "name": v["name"], "gender": v["gender"], "voice_id": v["voice_id"],
                             "seconds": duration(out / f)})
        check(previews, out)
        (out / "samples.json").write_text(json.dumps(previews, ensure_ascii=False, indent=1), encoding="utf-8")
        for p_ in previews:
            print(f"{p_['n']}. {p_['name']} {p_['seconds']}s | {p_.get('heard', '')[:160]}")
        print("free previews only, no credits spent; set \"sample_tts\": true for custom-line samples")
        print("after:", credits(http))
        return
    want = int(cfg.get("samples", 3))
    picks = []                                    # the most used male and female voice first, then the next best
    for g in ("male", "female"):
        picks += [v for v in found if v.get("gender") == g and v not in picks][:1]
    picks += [v for v in found if v not in picks][: max(want - len(picks), 0)]
    picks = picks[:want]
    text = (cfg.get("sample_text") or spoken(cfg["lines"][0])).strip()
    if len(text) * len(picks) > max_chars:
        picks = picks[: max(max_chars // max(len(text), 1), 0)]
    result = []
    for i, v in enumerate(picks, 1):
        if v.get("preview_url"):
            try:
                (out / f"preview_{i}.mp3").write_bytes(httpx.get(v["preview_url"], timeout=60).content)
            except Exception:
                pass
        a = http.post(f"/v1/voices/add/{v['public_owner_id']}/{v['voice_id']}", json={"new_name": f"uk · {v['name']}"[:50]})
        voice_id = a.json().get("voice_id") if a.status_code < 400 else v["voice_id"]
        if a.status_code >= 400:
            print(f"add {v['name']}: {a.status_code} {a.text[:160]} (trying the shared id)")
        f = f"sample_{i}.mp3"
        tts(http, voice_id, text, cfg.get("model", DEFAULT_MODEL), cfg.get("voice_settings", DEFAULT_SETTINGS), out / f)
        result.append({"n": i, "file": f, "name": v.get("name"), "gender": v.get("gender"), "age": v.get("age"),
                       "voice_id": voice_id, "usage_1y": v.get("usage_character_count_1y"),
                       "description": v.get("description"), "text": text, "seconds": duration(out / f)})
        (out / "samples.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    check(result, out)
    (out / "samples.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in result:
        print(f"{s['n']}. {s['name']} ({s['gender']}, {s['age']}) {s['seconds']}s wer={s.get('wer')} | {s.get('heard', '')}")
    print("after:", credits(http))


# ---------------------------------------------------------------- render
def key_of(line: dict, cfg: dict) -> str:
    blob = json.dumps([spoken(line), cfg["voice_id"], cfg.get("model", DEFAULT_MODEL),
                       cfg.get("voice_settings", DEFAULT_SETTINGS)], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def render(cfg: dict, out: Path, cache: Path | None, max_chars: int) -> None:
    if not cfg.get("voice_id"):
        sys.exit("voice.json has no voice_id: run the samples mode first and pick one")
    out.mkdir(parents=True, exist_ok=True)
    old = {}
    if cache and (cache / "manifest.json").exists():
        old = json.loads((cache / "manifest.json").read_text(encoding="utf-8"))
    lines = cfg["lines"]
    todo = []
    manifest = {}
    for line in lines:
        k = key_of(line, cfg)
        manifest[line["id"]] = k
        if cache and old.get(line["id"]) == k and (cache / f"{line['id']}.mp3").exists():
            shutil.copy(cache / f"{line['id']}.mp3", out / f"{line['id']}.mp3")
        else:
            todo.append(line)
    need = sum(len(spoken(l)) for l in todo)
    print(f"{len(lines) - len(todo)} lines reused, {len(todo)} to generate, {need} characters (limit {max_chars})")
    if need > max_chars:
        sys.exit(f"would spend {need} characters, more than --max-chars {max_chars}: nothing generated")
    http = client()
    if todo and cfg.get("public_owner_id"):
        a = http.post(f"/v1/voices/add/{cfg['public_owner_id']}/{cfg['voice_id']}", json={"new_name": cfg.get("voice_name", "uk voice")[:50]})
        print(f"add voice to the library: {a.status_code} {a.text[:120]}")
    if todo:
        print("before:", credits(http))
    for line in todo:
        i = lines.index(line)
        ctx = cfg.get("context", False)            # neighbouring lines as context: smoother, but it made lines stutter
        prev = " ".join(spoken(l) for l in lines[max(i - 2, 0):i]) if ctx else ""
        nxt = (spoken(lines[i + 1]) if i + 1 < len(lines) else "") if ctx else ""
        tts(http, cfg["voice_id"], spoken(line), cfg.get("model", DEFAULT_MODEL),
            cfg.get("voice_settings", DEFAULT_SETTINGS), out / f"{line['id']}.mp3", prev, nxt)
    if todo:
        print("after:", credits(http))
    report = [{"id": l["id"], "file": f"{l['id']}.mp3", "text": spoken(l), "seconds": duration(out / f"{l['id']}.mp3"),
               "new": l in todo} for l in lines]
    check(report, out)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in report:
        print(f"{r['id']} {r['seconds']:5.2f}s {'new ' if r['new'] else 'kept'} wer={r.get('wer')} | {r.get('heard', '')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["samples", "render"])
    ap.add_argument("script")
    ap.add_argument("out")
    ap.add_argument("--cache")
    ap.add_argument("--max-chars", type=int, default=1500)
    a = ap.parse_args()
    cfg = json.loads(Path(a.script).read_text(encoding="utf-8"))
    if a.mode == "samples":
        samples(cfg, Path(a.out), a.max_chars)
    else:
        render(cfg, Path(a.out), Path(a.cache) if a.cache else None, a.max_chars)
    return 0


if __name__ == "__main__":
    sys.exit(main())
