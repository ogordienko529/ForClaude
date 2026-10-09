"""Record simulated raw gameplay footage with Luanti (open-source voxel game) on a virtual display.

This stands in for "a Minecraft recording someone hands to the editor": first-person play with
boring stretches (walking, looking around), building, and one big moment (TNT). Minecraft itself is
closed and needs an account, so the demo uses Luanti + Minetest Game, which look alike.

    sudo apt install minetest xvfb ffmpeg && pip install python-xlib
    python examples/gameplay_sim/record.py -o raw_gameplay.mp4

Input is sent with XTest (real mouse and keyboard events); world events (clearing trees, the
progressive house build, TNT) come from the `director` mod, driven through a command file.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from Xlib import X, XK, display
from Xlib.ext import xtest

HERE = Path(__file__).parent
W, H = 1280, 720
GAME = "/usr/games/minetest"

CONFIG = f"""
screen_w = {W}
screen_h = {H}
fullscreen = false
fps_max = 30
fps_max_unfocused = 30
pause_on_lost_focus = false
viewing_range = 70
leaves_style = simple
enable_3d_clouds = false
enable_shaders = true
smooth_lighting = true
mute_sound = true
mouse_sensitivity = 0.2
fixed_map_seed = 1234567
mg_name = v7
creative_mode = true
enable_damage = false
enable_tnt = true
tnt_radius = 4
"""


class Driver:
    """Real input events for the game window (keys, buttons, smooth relative mouse motion)."""

    def __init__(self, d: display.Display, cmd_file: Path, log_file: Path):
        self.d = d
        self.cmd_file = cmd_file
        self.log_file = log_file
        self.t0 = time.time()

    # --- low level
    def _key(self, name: str, down: bool) -> None:
        code = self.d.keysym_to_keycode(XK.string_to_keysym(name))
        xtest.fake_input(self.d, X.KeyPress if down else X.KeyRelease, code)
        self.d.sync()

    def tap(self, name: str, hold: float = 0.06) -> None:
        self._key(name, True)
        time.sleep(hold)
        self._key(name, False)

    def button(self, b: int, down: bool) -> None:
        xtest.fake_input(self.d, X.ButtonPress if down else X.ButtonRelease, b)
        self.d.sync()

    def command(self, line: str) -> None:
        with self.cmd_file.open("a") as f:
            f.write(line + "\n")

    # --- high level
    def look(self, yaw: float = 0.0, pitch: float = 0.0, seconds: float = 1.0, keys: tuple[str, ...] = ()) -> None:
        """Turn by yaw/pitch degrees with ease-in-out (positive yaw = right, positive pitch = down),
        optionally holding movement keys meanwhile."""
        px_per_deg = 1 / 0.2  # mouse_sensitivity 0.2 degrees per pixel
        steps = max(int(seconds * 60), 1)
        done_x = done_y = 0.0
        for k in keys:
            self._key(k, True)
        for i in range(1, steps + 1):
            f = 0.5 - 0.5 * math.cos(math.pi * i / steps)
            tx, ty = yaw * px_per_deg * f, pitch * px_per_deg * f
            dx, dy = round(tx - done_x), round(ty - done_y)
            if dx or dy:
                xtest.fake_input(self.d, X.MotionNotify, detail=1, x=dx, y=dy)
                self.d.sync()
                done_x += dx
                done_y += dy
            time.sleep(1 / 60)
        for k in keys:
            self._key(k, False)

    def walk(self, seconds: float, key: str = "w", sway: float = 6.0) -> None:
        """Walk with a little natural head movement."""
        n = max(int(seconds / 0.5), 1)
        self._key(key, True)
        for i in range(n):
            self.look(yaw=sway * math.sin(i * 1.3), pitch=1.5 * math.cos(i * 0.9), seconds=0.5)
        self._key(key, False)

    def aim(self, seconds: float = 1.0, keys: tuple[str, ...] = ()) -> None:
        """Turn smoothly to face the house (the director mod computes the angles)."""
        self.command("aim")
        time.sleep(0.25)
        lines = [l for l in self.log_file.read_text(errors="ignore").splitlines() if "[director] aim " in l]
        if not lines:
            return
        parts = dict(kv.split("=") for kv in lines[-1].split("aim ", 1)[1].split())
        # game yaw grows to the left; the mouse turns right for positive x
        self.look(yaw=-float(parts["dyaw"]), pitch=float(parts["dpitch"]), seconds=seconds, keys=keys)

    def idle(self, seconds: float) -> None:
        self.look(yaw=4, pitch=-2, seconds=seconds / 2)
        self.look(yaw=-5, pitch=2, seconds=seconds / 2)


def session(dr: Driver) -> None:
    """About 90 s of raw play: boring start, exploring, digging, a fast build, admiring, TNT."""
    dr.idle(3.0)                                     # nothing happens
    dr.walk(6.0)                                     # explore
    dr.tap("space")
    dr.walk(3.0)
    dr.look(yaw=-35, seconds=1.2)                    # look around
    dr.look(pitch=55, seconds=1.0)                   # look down and dig a hole
    dr.button(1, True)
    time.sleep(2.5)
    dr.button(1, False)
    dr.look(pitch=-55, seconds=1.0)
    dr.look(yaw=180, seconds=2.2)                    # turn to the building spot
    dr.command("build")                              # ~26 s of blocks appearing
    time.sleep(0.5)
    dr.tap("2")                                      # hotbar: wood
    dr.aim(1.0)
    for i in range(4):
        dr.look(yaw=-14, pitch=-5, seconds=1.5)
        dr.look(yaw=14, pitch=5, seconds=1.5)
        dr.tap("3" if i % 2 else "4")
        dr.look(yaw=6, seconds=1.1, keys=("a",))
        dr.aim(1.1, keys=("d",))
        dr.tap("2")
    dr.aim(0.8)
    dr.look(pitch=-4, seconds=1.2, keys=("s",))      # step back and admire
    dr.idle(3.0)
    dr.look(pitch=-40, seconds=1.5)                  # stare at the sky (boring)
    dr.idle(2.5)
    dr.aim(1.5)
    dr.tap("7")                                      # hotbar: TNT
    dr.command("tnt")
    time.sleep(1.6)
    dr.tap("8")                                      # flint and steel
    dr.command("ignite")
    dr.look(yaw=-3, seconds=0.8)
    dr.aim(0.8)
    time.sleep(3.0)                                  # boom happens here (4 s fuse)
    dr.aim(0.6)
    time.sleep(2.5)
    dr.tap("1")
    dr.walk(2.5, sway=2)                             # walk to the crater
    dr.aim(0.8)
    dr.look(pitch=25, seconds=1.2)
    dr.idle(3.5)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-o", "--out", default="raw_gameplay.mp4")
    ap.add_argument("--display", default=":95")
    ap.add_argument("--calibrate", action="store_true", help="turn 90 degrees and report the measured yaw")
    a = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="luanti_"))
    world = work / "world"
    (world / "worldmods").mkdir(parents=True)
    shutil.copytree(HERE / "director", world / "worldmods" / "director")
    (world / "world.mt").write_text("gameid = minetest_game\nbackend = sqlite3\ncreative_mode = true\nenable_damage = false\n")
    (work / "game.conf").write_text(CONFIG)
    cmd_file = world / "director_cmd.txt"

    env = dict(os.environ, DISPLAY=a.display, LP_NUM_THREADS=str(os.cpu_count() or 4))
    xvfb = subprocess.Popen(["Xvfb", a.display, "-screen", "0", f"{W}x{H}x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    game = subprocess.Popen([GAME, "--go", "--world", str(world), "--gameid", "minetest_game", "--name", "steve",
                             "--config", str(work / "game.conf")], env=env,
                            stdout=open(work / "game.log", "w"), stderr=subprocess.STDOUT)
    rec = None
    try:
        time.sleep(14)  # load the map
        d = display.Display(a.display)
        dr = Driver(d, cmd_file, work / "game.log")
        wid = subprocess.run(["xdotool", "search", "--name", "Minetest"], env=env, capture_output=True,
                             text=True).stdout.split()[0]
        subprocess.run(["xdotool", "windowfocus", "--sync", wid], env=env)
        subprocess.run(["xdotool", "mousemove", "--window", wid, str(W // 2), str(H // 2)], env=env)
        dr.tap("F2")  # hide the chat log, as most recorders do
        for c in ("day", "give", "clear 22"):
            dr.command(c)
        time.sleep(4)
        if a.calibrate:
            dr.command("report")
            time.sleep(0.5)
            dr.look(yaw=90, seconds=1.5)
            time.sleep(0.5)
            dr.command("report")
            time.sleep(0.5)
            print("\n".join(l for l in (work / "game.log").read_text().splitlines() if "report " in l))
            return
        rec = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "x11grab", "-framerate", "30", "-video_size",
                                f"{W}x{H}", "-i", a.display, "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                                "-pix_fmt", "yuv420p", a.out], env=env, stdin=subprocess.PIPE)
        session(dr)
    finally:
        if rec:
            rec.communicate(b"q", timeout=30)
        game.terminate()
        game.wait(timeout=20)
        xvfb.terminate()
        shutil.rmtree(work, ignore_errors=True)
    print(a.out)


if __name__ == "__main__":
    main()
