"""CLI: python -m sleep_voice <command>

  render script.txt -o out.mp3     narrate a script (+ .srt subtitles and chapter timestamps)
  samples -o samples/              short demo of each male voice (and a few blends) to pick from
  voices                           list male voices
  estimate script.txt              how long the narration will be
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
import tomllib
from dataclasses import fields, replace
from pathlib import Path

from .engine import MALE_VOICES
from .master import Mastering, master, measure_loudness
from .render import Pacing, chapter_time, render, write_chapters, write_srt
from .text import parse_script

# Words per minute of pure speech at speed 1.0 (calibrated on a real Kokoro v1.0 render).
WPM_AT_SPEED_1 = 185

PRESETS: dict[str, tuple[dict, dict]] = {
    # name: (pacing overrides, mastering overrides)
    "sleep": ({}, {}),
    "deep": ({"speed": 0.84, "wind_down_speed": 0.76, "sentence_pause": 1.1, "paragraph_pause": 2.6,
              "wind_down_pause_scale": 1.5}, {"loudness_lufs": -22.0, "lowpass_hz": 8000}),
    "calm": ({"speed": 0.94, "wind_down_speed": 0.9, "sentence_pause": 0.6, "paragraph_pause": 1.4,
              "wind_down_pause_scale": 1.15}, {"loudness_lufs": -18.0, "lowpass_hz": 11000}),
}

SAMPLE_TEXT = """# The Lighthouse at Night

The keeper climbed the spiral stairs one last time that evening. Outside, the sea was calm, and the lamp turned slowly, sweeping its pale light across the water.

In 1888, a keeper's log recorded nothing more than the weather. Wind from the west. A little rain after midnight. The lamp was trimmed at 4 AM, and the kettle was put on the stove."""


def load_lexicon(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    with open(path, "rb") as fh:
        return {str(k): str(v) for k, v in tomllib.load(fh).items()}


def build(args) -> tuple[Pacing, Mastering]:
    pace_o, master_o = PRESETS[args.preset]
    pacing = replace(Pacing(), **pace_o)
    mastering = replace(Mastering(), **master_o)
    for f in fields(Pacing):
        v = getattr(args, f.name, None)
        if v is not None:
            pacing = replace(pacing, **{f.name: v})
    for name in ("loudness_lufs", "background", "background_db"):
        v = getattr(args, name, None)
        if v is not None:
            mastering = replace(mastering, **{name: v})
    return pacing, mastering


def estimate_seconds(script, pacing: Pacing) -> float:
    avg_speed = (pacing.speed + pacing.wind_down_speed) / 2
    speech = script.word_count() / (WPM_AT_SPEED_1 * avg_speed) * 60
    avg_scale = (1 + pacing.wind_down_pause_scale) / 2
    pauses = 0.0
    for s in script.segments:
        if s.kind == "pause":
            pauses += s.seconds
        else:
            pauses += {"sentence": pacing.sentence_pause, "paragraph": pacing.paragraph_pause,
                       "chapter": pacing.chapter_pause}[s.after] * avg_scale
    return speech + pauses + 8.0  # + lead-in and tail silence


def engine_from_args(args, voice: str | None = None):
    from .engine import make_engine

    opts = {}
    if args.engine == "openai" and args.instructions:
        opts["instructions"] = args.instructions
    if args.engine == "chatterbox":
        opts.update(exaggeration=args.exaggeration, cfg_weight=args.cfg_weight)
    return make_engine(args.engine, voice if voice is not None else args.voice, **opts)


def cmd_render(args) -> int:

    pacing, mastering = build(args)
    script = parse_script(Path(args.script).read_text(encoding="utf-8"), load_lexicon(args.lexicon))
    if not script.sentences:
        print("error: the script has no text", file=sys.stderr)
        return 2
    out = Path(args.output)
    est = estimate_seconds(script, pacing)
    print(f"{script.word_count():,} words, {len(script.sentences)} sentences -> about {chapter_time(est)} of audio",
          file=sys.stderr)
    engine = engine_from_args(args)
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.wav" if not args.no_master else out.with_suffix(".wav")
        result = render(script, engine, raw, pacing, unit=args.unit)
        if args.no_master:
            final = raw
        else:
            print("Mastering...", file=sys.stderr)
            master(raw, out, result.duration, mastering)
            final = out
    if not args.no_srt:
        write_srt(result.cues, out.with_suffix(".srt"))
    if result.chapters:
        write_chapters(result.chapters, out.with_suffix(".chapters.txt"))
    print(f"Done: {final} ({chapter_time(result.duration)}, {result.synthesized} sentences synthesized, "
          f"{result.cached} from cache, {(time.time() - started) / 60:.1f} min)", file=sys.stderr)
    if not args.no_master:
        print(f"Loudness: {measure_loudness(final):.1f} LUFS", file=sys.stderr)
    return 0


def cmd_samples(args) -> int:
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    pacing, mastering = build(args)
    text = Path(args.text).read_text(encoding="utf-8") if args.text else SAMPLE_TEXT
    script = parse_script(text)
    defaults = {
        "kokoro": ["am_michael", "am_onyx", "bm_george", "bm_lewis", "am_michael:0.6,bm_george:0.4",
                   "am_onyx:0.5,am_michael:0.5"],
        "openai": ["onyx", "ash", "cedar", "echo", "sage"],
    }
    voices = args.voices or defaults.get(args.engine, [None])
    with tempfile.TemporaryDirectory() as tmp:
        for v in voices:
            name = f"{args.engine}_" + (str(v) if v else "default").replace(":", "").replace(",", "+").replace(".", "").replace("/", "_")
            res = render(script, engine_from_args(args, v), Path(tmp) / f"{name}.wav", pacing, unit=args.unit,
                         log=lambda m: None)
            master(Path(tmp) / f"{name}.wav", outdir / f"{name}.mp3", res.duration, mastering)
            print(f"  {outdir / (name + '.mp3')}  ({chapter_time(res.duration)})")
    return 0


def cmd_voices(_args) -> int:
    for v, note in MALE_VOICES.items():
        print(f"  {v:12} {note}")
    print("\nBlend voices for your own stable timbre, e.g. --voice am_michael:0.6,bm_george:0.4")
    return 0


def cmd_estimate(args) -> int:
    pacing, _ = build(args)
    script = parse_script(Path(args.script).read_text(encoding="utf-8"))
    est = estimate_seconds(script, pacing)
    per_hour = script.word_count() / (est / 3600) if est else 0
    print(f"{script.word_count():,} words -> about {chapter_time(est)}; "
          f"≈{per_hour:,.0f} words per hour at preset '{args.preset}'")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sleep_voice", description="Calm English male narration for sleep videos")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def engine_args(p):
        p.add_argument("--engine", choices=["kokoro", "chatterbox", "openai", "elevenlabs"], default="kokoro",
                       help="kokoro (free, CPU) | chatterbox (free, GPU, most natural open model) | "
                            "openai (OPENAI_API_KEY, ~$0.015/min) | elevenlabs (ELEVENLABS_API_KEY)")
        p.add_argument("--unit", choices=["paragraph", "sentence"], default=None,
                       help="speak whole paragraphs (natural intonation, default) or single sentences")
        p.add_argument("--instructions", help="openai: custom style instructions")
        p.add_argument("--exaggeration", type=float, default=0.3, help="chatterbox: expressiveness (0.25-0.5 calm)")
        p.add_argument("--cfg-weight", dest="cfg_weight", type=float, default=0.35, help="chatterbox: lower = slower")

    def pacing_args(p):
        p.add_argument("--preset", choices=list(PRESETS), default="sleep")
        p.add_argument("--speed", type=float, help="start speed (default 0.88)")
        p.add_argument("--wind-down-speed", dest="wind_down_speed", type=float, help="speed at the end (default 0.80)")
        p.add_argument("--sentence-pause", dest="sentence_pause", type=float)
        p.add_argument("--paragraph-pause", dest="paragraph_pause", type=float)
        p.add_argument("--chapter-pause", dest="chapter_pause", type=float)
        p.add_argument("--seed", type=int)
        p.add_argument("--loudness", dest="loudness_lufs", type=float, help="target LUFS (default -20)")
        p.add_argument("--background", help="none | brown | pink | path/to/rain.wav")
        p.add_argument("--background-db", dest="background_db", type=float, help="bed level vs voice (default -30)")

    p = sub.add_parser("render", help="narrate a script")
    p.add_argument("script")
    p.add_argument("-o", "--output", required=True, help=".mp3 / .m4a / .wav / .flac")
    p.add_argument("--voice", default=None,
                   help="kokoro: voice or blend (am_michael:0.6,bm_george:0.4); openai: onyx/ash/cedar...; "
                        "elevenlabs: voice_id; chatterbox: path to a reference WAV to clone")
    p.add_argument("--lexicon", help="TOML file of word = \"respelling\" pronunciation fixes")
    p.add_argument("--no-master", action="store_true", help="skip ffmpeg mastering (raw WAV)")
    p.add_argument("--no-srt", action="store_true")
    pacing_args(p)
    engine_args(p)
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("samples", help="demo each male voice to choose from")
    p.add_argument("-o", "--output", default="voice_samples")
    p.add_argument("--text", help="custom sample script")
    p.add_argument("--voices", nargs="*")
    pacing_args(p)
    engine_args(p)
    p.set_defaults(fn=cmd_samples)

    sub.add_parser("voices", help="list male voices").set_defaults(fn=cmd_voices)

    p = sub.add_parser("estimate", help="estimate narration length")
    p.add_argument("script")
    pacing_args(p)
    p.set_defaults(fn=cmd_estimate)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
