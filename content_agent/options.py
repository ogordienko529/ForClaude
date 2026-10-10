"""Options the agent proposes before producing anything: video ideas, or edit variants of a recording.

A batch is saved as JSON (for --pick) and as Markdown (to read). The user picks by number and the
agent makes the chosen ones, in the same session when possible.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

KINDS = {"ideas": "ідеї відео", "edit_variants": "варіанти монтажу запису"}
FORMATS = {"short": "Шортс 9:16", "explainer": "пояснювальне відео 16:9", "review": "огляд 16:9"}
REQUIRED = ("title", "format", "pitch", "why", "needs", "length")
OPTIONAL = ("titles", "hook", "moments", "style", "effort", "sources")


def options_dir(root: Path) -> Path:
    d = root / ".agent" / "options"
    d.mkdir(parents=True, exist_ok=True)
    return d


def check(options: list[dict]) -> list[str]:
    errors = []
    if not 2 <= len(options) <= 6:
        errors.append(f"propose 2-6 options, got {len(options)}")
    for i, o in enumerate(options, 1):
        if not isinstance(o, dict):
            errors.append(f"option {i} is not an object")
            continue
        missing = [k for k in REQUIRED if not str(o.get(k, "")).strip()]
        if missing:
            errors.append(f"option {i}: missing {', '.join(missing)}")
        if o.get("format") and o["format"] not in FORMATS:
            errors.append(f"option {i}: format must be one of {tuple(FORMATS)}")
        unknown = set(o) - set(REQUIRED) - set(OPTIONAL)
        if unknown:
            errors.append(f"option {i}: unknown fields {sorted(unknown)} (allowed: {REQUIRED + OPTIONAL})")
    return errors


def save(root: Path, kind: str, context: str, options: list[dict], project: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {tuple(KINDS)}")
    errors = check(options)
    if errors:
        raise ValueError("; ".join(errors))
    bid = time.strftime("%Y%m%d-%H%M%S")
    batch = {"id": bid, "created": time.time(), "kind": kind, "context": context.strip(), "project": project,
             "files": [], "session": None, "options": options}
    d = options_dir(root)
    path = d / f"{bid}.json"
    path.write_text(json.dumps(batch, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    md = d / "latest.md"
    md.write_text(to_markdown(batch), encoding="utf-8")
    return {"id": bid, "json": str(path), "markdown": str(md)}


def latest(root: Path) -> tuple[Path, dict] | None:
    files = sorted(options_dir(root).glob("*.json"))
    if not files:
        return None
    return files[-1], json.loads(files[-1].read_text(encoding="utf-8"))


def update(path: Path, **fields) -> None:
    batch = json.loads(path.read_text(encoding="utf-8"))
    batch.update(fields)
    path.write_text(json.dumps(batch, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _join(v) -> str:
    return " / ".join(map(str, v)) if isinstance(v, list) else str(v)


def to_markdown(batch: dict) -> str:
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(batch["created"]))
    lines = [f"# Варіанти: {KINDS[batch['kind']]} ({when})", ""]
    if batch.get("context"):
        lines += [batch["context"], ""]
    for i, o in enumerate(batch["options"], 1):
        lines.append(f"## {i}. {o['title']} · {FORMATS.get(o['format'], o['format'])} · {o['length']}")
        lines.append(o["pitch"])
        lines.append(f"- **Чому може зайти:** {o['why']}")
        lines.append(f"- **Що потрібно від тебе:** {o['needs']}")
        for key, label in (("hook", "Хук"), ("moments", "Моменти із запису"), ("style", "Стиль"),
                           ("effort", "Скільки часу"), ("titles", "Варіанти назви"), ("sources", "Джерела")):
            if o.get(key):
                lines.append(f"- **{label}:** {_join(o[key])}")
        lines.append("")
    n = len(batch["options"])
    lines.append(f"Обрати: `content-agent agent --pick N` (1–{n}); кілька: `--pick 1,3`.")
    return "\n".join(lines) + "\n"


def parse_pick(spec: str, count: int) -> list[int]:
    nums = []
    for part in spec.replace(" ", "").split(","):
        if not part.isdigit() or not 1 <= int(part) <= count:
            raise ValueError(f"pick numbers between 1 and {count}, e.g. --pick 2 or --pick 1,3 (got {spec!r})")
        if int(part) not in nums:
            nums.append(int(part))
    return nums


def pick_message(batch: dict, nums: list[int], note: str = "") -> str:
    chosen = [batch["options"][n - 1] for n in nums]
    names = ", ".join(f"{n} «{o['title']}»" for n, o in zip(nums, chosen))
    lines = [f"The user picked option {names} from the {batch['kind'].replace('_', ' ')} you proposed."]
    if note.strip():
        lines.append(f"The user adds: {note.strip()}")
    lines.append("Make " + ("it" if len(chosen) == 1 else "them one after another") +
                 " now: follow the full workflow to a finished, self-reviewed video, then report in Ukrainian.")
    lines.append("Chosen option details (JSON):")
    lines.append(json.dumps(chosen, indent=1, ensure_ascii=False))
    if batch.get("context"):
        lines.append(f"Context of the proposal: {batch['context']}")
    return "\n".join(lines)
