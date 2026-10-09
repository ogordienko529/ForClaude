"""Which mods are in a recording: read them from the game's log or the mods folder.

Minecraft writes the loaded mods to `.minecraft/logs/latest.log` (Fabric/Quilt: a "Loading N mods:"
list; Forge/NeoForge: "Found valid mod file ... with {modid} mods - versions {x}"). A folder of
.jar files works too. Luanti: a world folder (world.mt `load_mod_* = true`) or a mods folder.
The agent then looks every mod up on its official page (Modrinth / CurseForge / ContentDB) for the
real name, author, features and licence before writing anything about it.
"""

from __future__ import annotations

import re
from pathlib import Path

PLATFORM = {"java", "minecraft", "fabricloader", "quilt_loader", "forge", "neoforge", "mixinextras", "fml"}

_FABRIC_HEAD = re.compile(r"Loading \d+ mods:\s*$")
_FABRIC_LINE = re.compile(r"^\s*-\s+([A-Za-z0-9_.\-]+)\s+(\S+)")
_FORGE = re.compile(r"Found valid mod file (\S+) with \{([^}]*)\} mods - versions \{([^}]*)\}")
_JAR = re.compile(r"^(.+?)[-_ ]v?(\d[\w.+\-]*?)(?:[-_](?:fabric|forge|neoforge|quilt))?\.jar$", re.I)


def parse_log(text: str) -> list[dict]:
    mods: dict[str, dict] = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _FABRIC_HEAD.search(line):
            for nxt in lines[i + 1:]:
                if "|--" in nxt:  # bundled sub-mods
                    continue
                m = _FABRIC_LINE.match(nxt)
                if not m:
                    break
                mods.setdefault(m.group(1), {"id": m.group(1), "version": m.group(2), "loader": "fabric"})
        m = _FORGE.search(line)
        if m:
            ids = [x.strip() for x in m.group(2).split(",") if x.strip()]
            versions = [x.strip() for x in m.group(3).split(",")]
            for k, mid in enumerate(ids):
                mods.setdefault(mid, {"id": mid, "version": versions[k] if k < len(versions) else "",
                                      "loader": "forge", "file": m.group(1)})
    return [dict(m, platform=m["id"] in PLATFORM) for m in mods.values()]


def parse_mods_dir(path: Path) -> list[dict]:
    out = []
    for jar in sorted(Path(path).glob("*.jar")):
        m = _JAR.match(jar.name)
        out.append({"id": m.group(1) if m else jar.stem, "version": m.group(2) if m else "", "file": jar.name,
                    "loader": "", "platform": False})
    for conf in sorted(Path(path).glob("*/mod.conf")):  # Luanti mods folder
        name = re.search(r"^name\s*=\s*(\S+)", conf.read_text(errors="ignore"), re.M)
        out.append({"id": name.group(1) if name else conf.parent.name, "version": "", "loader": "luanti",
                    "platform": False})
    return out


def parse_luanti_world(world: Path) -> list[dict]:
    text = (Path(world) / "world.mt").read_text(errors="ignore")
    ids = re.findall(r"^load_mod_(\S+)\s*=\s*true", text, re.M)
    ids += [p.parent.name for p in (Path(world) / "worldmods").glob("*/mod.conf")]
    return [{"id": i, "version": "", "loader": "luanti", "platform": False} for i in dict.fromkeys(ids)]


def load_mods(path: Path) -> list[dict]:
    path = Path(path)
    if path.is_dir():
        if (path / "world.mt").exists():
            return parse_luanti_world(path)
        return parse_mods_dir(path)
    return parse_log(path.read_text(errors="ignore"))
