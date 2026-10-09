---
name: edit-gameplay
description: Turn raw gameplay footage (Minecraft and similar) into a fast, punchy vertical Short with no voice-over - find the moments, cut on the beat, zoom, freeze, add meme text, SFX and a drop, then self-review. Use when the user gives a gameplay recording and wants it edited, or asks for a dynamic/fast edit.
---

# Edit gameplay into a fast vertical Short (local, $0)

You are the editor. `content_agent` does the mechanical work locally: footage analysis, procedural
beat music and SFX (no licences, nothing for Content ID to match), Remotion render at 1080x1920, QA.

```
python -m content_agent footage <slug> raw.mp4      # copy + analyse + footage sheets, creates edit.json
python -m content_agent validate <slug>             # checks edit.json
python -m content_agent make <slug>                 # build soundtrack + timeline -> render -> qa
python -m content_agent still <slug> s04 --at 0.5   # one frame of a segment (check framing)
```

## 1. Watch the footage

Open every `review/<video>/footage_*.png` (one frame per second, timecodes, blue bar = motion,
orange bar = burst: fire, explosions). Read the `events` (burst / action) and `idle` lists the
`footage` command prints. For the key moments, make a finer strip, e.g.
`ffmpeg -ss 63.5 -t 9 -i footage/raw.mp4 -vf "fps=4,scale=256:-1,tile=9x4" -frames:v 1 strip.png`,
and find the exact frame of the payoff (the first frame that changes).

Write down: the payoff (the one moment the Short is about), the setup that makes it land, the
boring parts (cut, or speed them up), and one frame that explains the video at a glance (the hook).

## 2. Structure (15-30 s; small-channel Minecraft hits are 19-38 s, median about 25 s)

1. **Hook, 0-2 s:** the subject visible in the first frame, plus text that creates a question or
   invites a comment ("Rate my house 1-10", "Noob vs Pro", "Wait for the end"). No intro, no logo.
2. **Setup, fast:** the journey in 1-3 s pieces; boring stretches at x4-x8 with a speed badge.
3. **Tension:** push-in zoom, riser SFX, then a freeze frame (black and white, "Wait...") where
   the music stops.
4. **Payoff on the drop:** the cut lands on the first frame of the action; slow-mo 0.5x,
   shake + flash, boom SFX; the beat drops here (`music.drop` = this segment).
5. **Aftermath and loop:** the reaction text ("NOOO"), one more twist if there is one, and an end
   that leads back to the hook ("Rate it now 1-10" calls back to "Rate my house 1-10").

## 3. edit.json rules

- Lengths in **beats** (`"beats": 2..6`, 140 bpm: 1 beat = 0.43 s) so every cut is on the beat.
  Source span = beats x 0.43 s x speed: check it does not run into the next event of the footage.
- Something must change at least every ~2 s (cut, zoom, text, badge). Segments 0.8-2.6 s.
- `focus` is where the action is in the source frame (x, y fractions). In crop mode the 9:16
  window is only 32% of a 16:9 frame wide, so aim it carefully. Use `"framing": "fit"` for wide shots
  and timelapses where the whole frame matters.
- Text: 1-6 words, uppercase meme style, highlight the key word with `*word*`; styles `hook` (top),
  `caption` (middle), `big` (reaction words), `label` with `target` (arrow to something).
  Text never covers the action.
- SFX: `whoosh` on speed changes/transitions, `riser` before the payoff, `boom` on it, `hit` on a
  reaction, `ding` on a success, `pop` is added to texts automatically. Not on every cut.
- Effects: `punch` for an instant zoom-in on a cut, `zoom`->`zoom_to` for push-ins/pull-outs,
  `fx: ["shake", "flash"]` only on impacts, `"bw"` for freeze/"flashback" moments.

## Style

`"style"` in edit.json sets the text look and the cut transition. Options are `meme` (outlined
uppercase, default), `boxed` (words on coloured boxes), `pixel` (pixel font and tooltip boxes),
`comic` (speech bubbles), `neon` (glow) and `clean` (white boxes). `python -m content_agent styles`
describes them. Match the video's mood, and rotate styles between videos and series so the channel
does not look templated (repetitive Shorts are what YouTube demonetises). A segment can override its
cut with `"transition"` (cut, zoomblur, pixel, flash, glitch, whip). Use that for the payoff or a
twist only.

## 4. Review and fix (at least one full round)

After `make`, read `review/qa.md` (pacing, hook, loudness), then open `review/overview.png` and
`review/sheet_*.png`. Check every segment: is the subject visible in the first frame? Does the
crop show the action? Is the text readable and off the action? Does the payoff frame land on the
cut? Score the rubric in `qa.md`, write `review/review.json`, fix `edit.json`, re-run `make`.
Use `still` to check a single segment's framing before a full render.

## Rules

- Footage must be the user's own (or licensed). Do not download other creators' videos; reused
  clips without real transformation are not monetisable and can get the channel demonetised.
- Use only the generated music and SFX. Trending songs and meme sounds are usually copyrighted.
- Do not put other creators' characters or channel names in titles to borrow their audience.
- Minecraft content is often watched by kids: keep text clean and set "made for kids" honestly.
