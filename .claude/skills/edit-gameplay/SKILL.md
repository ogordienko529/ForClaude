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

## 2. Structure: hook → stakes → escalation → payoff → loop

**Goal.** At least 70% of viewers stay past the first second: YouTube Studio's "viewed vs swiped
away". Under 60%, the hook is broken. Most viewers should watch to the end; a loop pushes average
percentage viewed past 100%.

**Length.** Default to 20–30 s; length must be earned by escalation, never padded. Small-channel
breakout Shorts (YouTube API, 60 days to October 2026) run:
- Minecraft drone Shorts: 9–29 s, median ~15 s;
- gun mods: median ~27 s;
- war mods: median ~36 s.

A 58 s Short with a 14 s average view is the typical failure: too long for what happens in it.

| Part | Time (25 s Short) | What happens |
|---|---|---|
| **Hook** | 0–1.5 s | The first frame works as a thumbnail: the action, or the payoff itself, already in view. 2–5 words that raise a question or a claim ("1 drone vs 50 zombies", "Wait for it", "Rate my base 1-10"). Text on the first frame. No intro, logo, slow pan or establishing shot. |
| **Stakes** | by ~5 s | What we are waiting for, or what is at risk, in one short text or a clear shot. |
| **Escalation** | middle | Every segment raises the stakes: bigger, closer, faster, worse. A pattern break every 2–3 s (cut, zoom, speed change, text, SFX). At 35–65% a **re-hook**: a counter, "round 2", "3 left", a freeze "wait…". Boring stretches at x4–x8 with a speed badge, or cut. |
| **Payoff** | last third | The biggest moment, set up by a riser, a push-in and a freeze where the music stops. The cut lands on its first frame. Then slow-mo 0.5x, shake + flash, boom, and the drop (`music.drop` = this segment). |
| **Loop** | last 1–3 s | One reaction beat, then end on a frame or line that leads back into the hook. Examples: "Rate it now 1-10" answers "Rate my base 1-10"; the last shot is the first shot before the action. No outro, no "subscribe" card, no fade to black. |

**Opening on the payoff.** You may put the payoff first as the hook, then show "3 minutes
earlier…" and rebuild to it. In that case the end must deliver a second, bigger payoff or a twist.

**Kill list** (viewers swipe on these):
- a slow first shot;
- more than 2 texts at once, or walls of small HUD-style labels;
- text that is on screen for less than 0.7 s;
- the same shot twice in a row;
- more than 2 s without a change;
- anything more than 3 s after the payoff.

`validate` warns about each of these: length, hook segment and text, a calm first shot (from the
footage analysis), a missing or early payoff, the tail after the payoff, a missing re-hook, and text
density. Treat these warnings as must-fix unless you can say why the edit is better without the fix.

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

## 5. Learn from the analytics

When the user shares YouTube Studio numbers or a screenshot, save them to
`content_projects/<slug>/analytics.md`: views, "viewed vs swiped away", average view duration,
length and the date. Then fix the cause:

| Signal | Cause | Fix |
|---|---|---|
| Viewed < 60% (swiped > 40%) | the first frame and hook text | Open on the action or the payoff, put 2–5 words of question or claim on the first frame, cut the hook to ≤ 1.5 s. |
| Average view < 50% of the length | too long, or the middle sags | Cut to the strongest 20–30 s, add escalation and a re-hook at 35–65%, speed up or drop setup. |
| Viewers leave right after the big moment | the payoff came too early | Move it to the last third, or open on it and rebuild to a second payoff. |
| Average view near 100% but few views | the hook works for few people | Make the topic broader and the hook text more curious; try another style. |
| Average view under 100% on a short clip | no replay | End on a frame or line that loops into the hook. |

Compare with the channel's own previous Shorts of similar length. YouTube publishes no official
benchmark, so the thresholds above are guidance from creator studies.

## Rules

- Footage must be the user's own (or licensed). Do not download other creators' videos; reused
  clips without real transformation are not monetisable and can get the channel demonetised.
- Use only the generated music and SFX. Trending songs and meme sounds are usually copyrighted.
- Do not put other creators' characters or channel names in titles to borrow their audience.
- Minecraft content is often watched by kids: keep text clean and set "made for kids" honestly.
