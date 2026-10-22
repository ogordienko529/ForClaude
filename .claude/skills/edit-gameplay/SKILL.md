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

## 1b. Pick the format first (what reaches 100k)

Set `"format"` in edit.json. It sets the length window, the loop rule and the QA feed checks.
The data: 57 Shorts with 100k+ views on channels under 10k subscribers found by Minecraft queries, YouTube
API, 30 days to 21 October 2026 (`niche_core scan @examples/seeds/formats.txt --days 30 --max-subs 10000`).
YouTube search mixes in other games: 6 of the 57 did not name Minecraft and 5 were Teardown, Blender or GTA
edits. The scan now drops those (`--require`, `--exclude`); check the game before you copy a format.
Plain moments from a playthrough were rare among them. The winners had a premise you get in one
second, and many titles carried no searchable words at all, so the feed, not search, pushed them.

| Format | Length | Breakouts (views, length, channel size) | Recipe |
|---|---|---|---|
| `test` | 15-40 s | "1 To 25000 Emeralds Vs Minecraft Villager!" 1.8M, 33 s, 5k (made in Teardown, not Minecraft); "Every Pixel You Mine Earn $0.005" 3.6M, 33 s, 8.9k; "Can i pass it?..." 2.0M, 21 s | the question is the hook text; frame 1 shows both sides and the counter at its first value; the counter rises every 1-3 s, each step bigger; the result in the last third; end on the counter or "again?" |
| `showcase` | 20-35 s | "Cool Hole Filler Mod..." 3.8M, 34 s, 9.5k; "GUNGNIR The Shooting Star Minecraft Mod" 1.1M, 27 s, 4.1k | frame 1 is the effect itself, never the crafting; 3-4 uses, each more extreme; the mod name as a small label (viewers always ask); the biggest use last |
| `story` | 35-60 s | "TRYING TO FIND THE REAL JERRY" 4.3M, 48 s, 7.9k; "Where am I?" 1.8M, 54 s, 4.3k; "The Horror Mob Came to Take the Fat Villager" 1.3M, 38 s, 8.3k | frame 1 is the threat or the strangest moment; the first line (text or chat) is the question; 3-5 beats, each raising the stakes; the answer in the last 5-10 s; no loop needed |
| `meme` | 6-25 s | "Hey it's me it's verity" 9.2M, 34 s, 9.6k; "The old faithful" 2.4M, 7 s, 3.8k; "Smart baby villagers" 1.3M, 17 s | one relatable situation; setup in frame 1, punchline at 70-90%; no explaining text; cut back to the setup frame to loop |
| `build` | 25-45 s | "I Built a FLYING Star Destroyer in Minecraft!" 2.1M, 35 s, 3.9k | 1 s of the finished build doing its thing, then the build-up as a fast timelapse, the full reveal last |
| `moment` | 15-30 s | (rare) | only with a premise in the hook text; otherwise pick another format |

Formats this channel cannot copy: 3D or LEGO animation, clips of other streamers' SMPs, phone tests.

**Reference Shorts for `test` (watch them before editing one; views on 21 Oct 2026):**
- "Can ANY explosion break OBSIDIAN? Kevin is hiding inside" (seedpite, 812k, 33 s): a ladder of
  explosions, 1 TNT, 10 TNT, 10 charged creepers..., with a character at stake.
  https://www.youtube.com/shorts/gZkai9_7jPc
- "1000 TNT with POWER 20 vs Cow AND Villager" (Hollow Point, 6.8k subs, 740k, 55 s): "did they survive?".
  https://www.youtube.com/shorts/w1_PbKVk9ZM
- "I Tested a Dark Sniffer's Happiness Meter in Minecraft... Part 2" (Pixalotyl, 933 subs, 585k, 20 s): a
  meter as the counter, "watch the meter to the end". https://www.youtube.com/shorts/9pU-t-qV7zs
- "Every Pixel You Mine Earn $0.005" (JustJinx, 8.9k subs, 3.6M, 33 s): a money counter.
  https://www.youtube.com/shorts/MnkRGkVkYSQ
- "MINECRAFT SCARY but nuking horror mods godzilla" (JohnnyXD Random, 13k subs, 411k, 77 s): this channel's
  topic; compare with "Bloodbath Godzilla vs a Nuke" (5.9k). https://www.youtube.com/shorts/Q9V5pSkgbHM
- "HOW MANY PIGS CAN ONE SPEAR KILL?" (Superoid Man, 1.5M, 82 s). https://www.youtube.com/shorts/gI5wD4qjvuY
- "How much fall damage can Steve take on different type of blocks" (super epic, 6.0M, 60 s).
  https://www.youtube.com/shorts/PCwdcvWftmE
- "the BEST minecraft ARMOUR" (CoreCraft, 3.7M, 16 s). https://www.youtube.com/shorts/EvZID9x3RbA
- "1 Regular TNT vs. 1,000 Mini TNT in Minecraft!" (MineStorm, 4.3k subs, 46k, 27 s): the same idea as bigger
  hits, far fewer views; compare its first 2 s with the ones above. https://www.youtube.com/shorts/xFLMZxp0QIg
- "1 To 25000 Emeralds Vs Minecraft Villager!" (Craft Destruction, 5.1k subs, 1.8M, 33 s; made in Teardown,
  but the cleanest 1-to-N structure). https://www.youtube.com/shorts/0Y3a-G1GPdw

**Feed readiness (QA checks the rendered file).** `qa` adds a "Feed readiness" table:
- hook text on screen by 0.5 s;
- the first 2 s move at least 0.6x as much as the rest (open on the action, not a calm shot);
- sound from the first frame (louder than -35 dBFS in the first 0.5 s);
- length inside the format's window;
- the last frame leads back into the first (colour difference <= 0.22) for every format except `story`.
- `review/first_frame.png`: the frames at 0.1 s and 1 s at phone size. Judge it by eye: the subject must fill
  a third of the frame height or more, and the premise must read from that frame alone. "Bloodbath Godzilla
  vs Every TNT" (2.3k, 61% viewed, 76% of views from search) showed Godzilla as a small dark shape in a big
  sky on its cover frame.
A high finding means the Short is not ready: fix it before upload.

**Targets after upload (Studio, 48 h):** viewed vs swiped >= 70% and average percentage viewed >= 90%
(loops count). This channel's best Short so far had 64% viewed and got 90% of its views from search:
the feed did not push it.

**Test formats like an experiment.** Make 3 Shorts in each of 2-3 formats, publish 1-2 a day, and log
views, viewed vs swiped and average percentage viewed at 48 h in `<project>/analytics.md`. Keep the format
that reaches 70% viewed or 3x the channel's median views; drop the rest. One week, then double down.

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

**Length depends on the kind of Short.** The numbers above are for *moment* Shorts (one clip,
one payoff, no voice). *News and explainer* Shorts ("Minecraft's new dimension explained", "I got
the new armour", "someone already added X") are a different animal: in the Sift wave (October
2026, small channels under 50k) the breakouts ran 36–157 s, median ~60 s, with narration, and a
14–16 s silent clip on the same topic did ~1k. Reasons: the viewer came for information, and a
long, narrated Short gets more watch time per view. So:
- a moment from gameplay → this playbook, 15–30 s, no voice;
- news, a tour, a test, "explained" → the narrated `shorts` format (`new <slug> --format shorts`,
  the `make-video` playbook) at 45–90 s, up to 3 min when every sentence adds something;
- a **story Short** from a horror or survival session → the same narrated `shorts` format, 45–60 s,
  in the creator's own voice (`voice_engine: recording`, the `review-video` playbook, section 4):
  one named character or threat, one night or one event, a question in the title, the answer in
  the last 10 s. Data (Verity, October 2026): the "Jerry" series on a 30k-sub channel, 57–59 s,
  0.9–9M per episode; the same topic as a 14 s silent clip did ~1k. Narration without the
  creator's voice is **off** on channels whose audit shows "AI voice" comments.
Name the thing in the title the way people search for it ("Sift", "Siftite", "Blub"), not a
paraphrase ("new dimension", "cutest mob").

**Principles, not a recipe.** Every Short has to satisfy these, but how it does so changes from
video to video. A channel where every Short has the same freeze, shake, flash and reaction word
looks like one template, and viewers call it AI.
- **The first frame sells it.** The action, or the payoff itself, is in view, no intro, logo or
  slow pan. If there is a text, it says something the picture does not.
- **Stakes early.** By ~5 s it is clear what we are waiting for or what is at risk.
- **Something new every 2–3 s.** It must change what the viewer knows, not just add an effect.
  Around the middle, something re-hooks.
- **Payoff in the last third**, prepared so it lands: the cut on its first frame.
- **End quickly** after it, on something that makes the replay feel natural. No outro.

**Technique bank.** Pick 3–5 per Short, and never the same set as the channel's last Shorts.
`validate` compares with them.

| Technique | What it does |
|---|---|
| Open on the payoff, then rebuild | curiosity: how did this happen? |
| Match cut | the same shape or motion across two moments (a drone dive into an explosion) |
| Cut on the game's sound | cuts land on shots and explosions instead of a music grid |
| Music drops out | silence before the hit, with the game sound only (instead of a freeze) |
| A held shot | 2–3 s without cuts while tension builds (a drone approaching) |
| Speed ramp | fast to slow on the moment, without a badge |
| Repeat from another angle | the same hit twice: first-person view, then from outside |
| Reverse reveal | play a destruction backwards into the build, then forwards |
| One push-in | a single slow zoom across the whole tension part, no punch-ins |
| Point of view only | the whole Short from the drone's camera |
| Counter on screen | the number does the talking: deaths, drones left, seconds |
| Freeze with no text | the frame says it, no "WAIT…" |
| Fit framing for scale | the whole wide frame when size matters |
| Quiet ending | the last 2 s with no text and no music, just the aftermath |
| Text only once | a single line, at the moment that needs it |
| A reaction in the creator's words | one line that sounds like the creator, not like a caption |

**Opening on the payoff.** You may put the payoff first as the hook, then rebuild to it. In that
case the end must deliver a second, bigger payoff or a twist.

**Kill list** (viewers swipe on these):
- a slow first shot;
- more than 2 texts at once, or walls of small HUD-style labels;
- text that is on screen for less than 0.7 s;
- the same shot twice in a row;
- more than 2 s without a change;
- anything more than 3 s after the payoff.

`validate` warns about each of these, about template tells (stock lines, generated music, markers)
and about sameness with the channel's last 3 edits (devices, music track, repeated lines). Treat
these warnings as must-fix unless you can say why the edit is better without the fix.

## 3. edit.json rules

- Lengths in **beats** (`"beats": 2..6`, 140 bpm: 1 beat = 0.43 s) so every cut is on the beat.
  Source span = beats x 0.43 s x speed: check it does not run into the next event of the footage.
- Something must change at least every ~2 s (cut, zoom, text, badge). Segments 0.8-2.6 s.
- `focus` is where the action is in the source frame (x, y fractions). In crop mode the 9:16
  window is only 32% of a 16:9 frame wide, so aim it carefully. Use `"framing": "fit"` for wide shots
  and timelapses where the whole frame matters.
- Text placement: `hook` (top), `caption` (middle), `big` (a rare reaction), `label` with `target`
  (an arrow to something). Text never covers the action.
- SFX on moments, not on every cut or text: `whoosh` on a speed change, `riser` before the payoff,
  `boom` on it, `hit` on a reaction, `ding` on a success.
- Effects: `punch` for an instant zoom-in on a cut, `zoom`->`zoom_to` for push-ins/pull-outs,
  `fx: ["shake", "flash"]` only on impacts, `"bw"` for a flashback.

## Text: the creator's voice, not captions

Viewers spot "AI editing" from the text first. One wrote, under a Short made with the old
defaults: "Ai editing, thats the AI text and also that music is ai, do better".

- **Few texts.** At most one per ~5 s, so 3–5 in a 25 s Short. A text exists only if it adds what
  the picture cannot: a stake ("last drone"), a number ("29 deaths"), a reaction or a joke in the
  creator's voice ("he really thought I was out of drones").
- **Never narrate the picture.** "STEP 1: DIG" over digging, "DONE!" over a finished house, "BOOM"
  over an explosion: the viewer already sees it.
- **No stock lines.** None of "WAIT…", "NOOO", "KABOOM", "X minutes earlier", "rate my X 1-10",
  "watch till the end", "?!", a trailing "…" on every line, or more than one highlighted word.
  `validate` flags all of these.
- **Write like the channel talks.** Use the "Voice" section of `content_projects/channel.md`: the
  creator's phrases, slang, language and what they never say. With no voice section, write short
  and lowercase, like a comment from a friend, not a headline.
- **Typography that does not shout.** Default to `"style": "plain"` (sentence case, no outline, no
  pop-in) with `"text_case": "as_written"`. Capitals and outlines are for one word in one moment,
  not for every line.
- **Template markers are off by default:** `progress_bar`, `sfx_on_text`, speed badges (one at
  most).
## Music and sound

The generated beat (`"style": "phonk" | "hype"`) sounds synthetic, and viewers call it AI music.
`validate` warns about it.
- **Use a real track** from the user's library: `music_library` (or `python -m content_agent
  music-lib`) lists each track's BPM and drops. Then:
  `"music": {"track": "file.mp3", "drop": "<payoff segment id>"}`.
  - Beat lengths follow the track's tempo.
  - The track is placed so its strongest drop lands on the payoff segment. Override with
    `"track_drop": <s>` or `"start": <s>`.
  - `out/credits.txt` gets the attribution line for the description.
- **Use the game's own sound.** `"game_audio": true` puts the recording's sound (shots, explosions,
  footsteps) under the music. For many Minecraft moments the real sound with quiet music, or no
  music at all (`"style": "none"`), feels more human than any beat.
- **Do not reuse a track** that the channel's previous Shorts used. When the library is empty, say
  so in the report and use game audio rather than the generated beat.

## Style

`"style"` in edit.json sets the text look and the cut transition. Options:
- `plain`: sentence case, plain text. The default, and the least templated.
- `meme`: outlined uppercase.
- `boxed`: words on coloured boxes.
- `pixel`: pixel font and tooltip boxes.
- `comic`: speech bubbles.
- `neon`: glow.
- `clean`: white boxes. `python -m content_agent styles`
describes them. Match the video's mood, and rotate styles between videos and series so the channel
does not look templated (repetitive Shorts are what YouTube demonetises). A segment can override its
cut with `"transition"` (cut, zoomblur, pixel, flash, glitch, whip). Use that for the payoff or a
twist only.

## 4. Review and fix (at least one full round)

**AI-look check, before the first render.** Answer honestly, and fix every "yes":
1. Does any text describe what is already on screen?
2. Would the creator really write each line? Read it aloud in their voice.
3. Is any device here only because it is "what Shorts do": a freeze, a shake, a flash, a reaction
   word?
4. Which 3 things are the same as the channel's last Short?
5. Is the music generated, or a track the channel already used?

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
