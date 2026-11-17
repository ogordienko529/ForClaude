"""Public data of one YouTube channel for a content audit, without an API key (yt-dlp).

Writes into OUT/:
- channel.json: name, description, subscribers, links, avatar and banner URLs;
- videos.json: every long video and Short (title, duration, views, date) and, for the newest and the most viewed
  ones, the full details (description, tags, chapters, likes, comments, category);
- transcripts/<id>.txt: the English captions (auto or manual) as plain text;
- thumbs.jpg: a contact sheet of the thumbnails with title, views and length under each;
- errors.txt: what could not be read (YouTube may ask a datacenter IP to sign in).

Usage: python yt_audit.py @handle OUT [--details 14]
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import yt_dlp
from PIL import Image, ImageDraw, ImageFont

errors: list[str] = []


def ydl(**opts):
    base = {"quiet": True, "no_warnings": True, "skip_download": True, "ignoreerrors": True, "extract_flat": False}
    base.update(opts)
    return yt_dlp.YoutubeDL(base)


def tab(handle: str, name: str) -> dict:
    url = f"https://www.youtube.com/{handle}/{name}"
    try:
        with ydl(extract_flat="in_playlist") as y:
            return y.extract_info(url, download=False) or {}
    except Exception as e:  # noqa: BLE001
        errors.append(f"{name}: {e}")
        return {}


def vtt_text(raw: str) -> str:
    """Plain text from a WebVTT file: no timings, tags or the rolling duplicates of auto captions."""
    out: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or line.isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and (not out or out[-1] != line):
            out.append(line)
    return " ".join(out)


def fetch(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except Exception as e:  # noqa: BLE001
        errors.append(f"fetch {url[:80]}: {e}")
        return None


def details(video_id: str, tdir: Path) -> dict:
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {"writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["en", "en-US", "en-orig"],
            "subtitlesformat": "vtt", "outtmpl": str(tdir / "%(id)s.%(ext)s")}
    try:
        with ydl(**opts) as y:
            info = y.extract_info(url, download=True) or {}
    except Exception as e:  # noqa: BLE001
        errors.append(f"{video_id}: {e}")
        return {}
    for vtt in sorted(tdir.glob(f"{video_id}*.vtt")):
        (tdir / f"{video_id}.txt").write_text(vtt_text(vtt.read_text(errors="ignore")))
        vtt.unlink()
        break
    keep = ("id", "title", "description", "duration", "view_count", "like_count", "comment_count", "upload_date",
            "tags", "categories", "chapters", "thumbnail", "channel_follower_count", "language", "availability")
    d = {k: info.get(k) for k in keep}
    d["has_transcript"] = (tdir / f"{video_id}.txt").exists()
    return d


def contact_sheet(items: list[dict], path: Path, cols: int = 4, w: int = 320) -> None:
    h = w * 9 // 16
    font = ImageFont.load_default()
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 40)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, it in enumerate(items):
        x, y = (i % cols) * w, (i // cols) * (h + 40)
        raw = fetch(f"https://i.ytimg.com/vi/{it['id']}/hqdefault.jpg")
        if raw:
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            # hqdefault is 4:3 with black bars: crop to the 16:9 picture
            iw, ih = im.size
            ch = iw * 9 // 16
            im = im.crop((0, (ih - ch) // 2, iw, (ih - ch) // 2 + ch)).resize((w, h))
            sheet.paste(im, (x, y))
        mins = (it.get("duration") or 0) / 60
        draw.text((x + 4, y + h + 2), (it.get("title") or "")[:52], fill="black", font=font)
        draw.text((x + 4, y + h + 18), f"{it.get('view_count') or 0:,} views · {mins:.0f} min", fill="#444", font=font)
    sheet.save(path, quality=72)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("handle")
    ap.add_argument("out")
    ap.add_argument("--details", type=int, default=14)
    a = ap.parse_args()
    out = Path(a.out)
    (out / "transcripts").mkdir(parents=True, exist_ok=True)

    vids = tab(a.handle, "videos")
    shorts = tab(a.handle, "shorts")
    lists = tab(a.handle, "playlists")
    channel = {k: vids.get(k) for k in ("channel", "channel_id", "uploader_id", "description", "channel_follower_count", "tags")}
    channel["thumbnails"] = [t.get("url") for t in (vids.get("thumbnails") or [])][-4:]
    channel["playlists"] = [{"title": p.get("title"), "id": p.get("id")} for p in (lists.get("entries") or []) if p]
    (out / "channel.json").write_text(json.dumps(channel, ensure_ascii=False, indent=1))

    def flat(entries):
        return [{"id": e.get("id"), "title": e.get("title"), "duration": e.get("duration"), "view_count": e.get("view_count")}
                for e in (entries or []) if e and e.get("id")]

    longs, shorts_l = flat(vids.get("entries")), flat(shorts.get("entries"))
    newest = longs[: a.details]
    top = sorted(longs, key=lambda v: v.get("view_count") or 0, reverse=True)[:6]
    picked = list({v["id"]: v for v in newest + top}.values())
    full = {}
    for v in picked:
        d = details(v["id"], out / "transcripts")
        if d:
            full[v["id"]] = d
    (out / "videos.json").write_text(json.dumps({"long": longs, "shorts": shorts_l, "details": full}, ensure_ascii=False, indent=1))
    contact_sheet(longs[:16], out / "thumbs.jpg")
    (out / "errors.txt").write_text("\n".join(errors))
    print(f"{len(longs)} videos, {len(shorts_l)} shorts, {len(full)} with details, "
          f"{len(list((out / 'transcripts').glob('*.txt')))} transcripts, {len(errors)} errors", file=sys.stderr)


if __name__ == "__main__":
    main()
