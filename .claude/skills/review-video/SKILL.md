---
name: review-video
description: Make a narrated mod review (Minecraft, Luanti and similar) from a silent gameplay recording - identify the mods, research them, write the script, voice it (Kokoro free or ElevenLabs), edit the footage to the narration with labels, chapters, a verdict card, a thumbnail and a YouTube description. Use when the user sends a recording for a mod review, showcase or "first look" video.
---

# Mod review from a silent recording

The user records gameplay **without talking**. You are the researcher, scriptwriter, narrator
director and editor. Everything renders locally with `content_agent` (format `review`, 16:9).

```
python -m content_agent new <slug> --title "..." --format review
python -m content_agent footage <slug> raw.mp4               # analysis + footage sheets (no edit.json for reviews)
python -m content_agent mods <slug> .minecraft/logs/latest.log   # or the mods folder / a Luanti world
python -m content_agent make <slug>                          # voice -> music -> mix -> build -> render -> qa
python -m content_agent thumbnail <slug>                     # out/thumbnail.png
```

`build` also writes `out/description.md` (chapters, credits, sources) and refuses to continue if a
footage scene needs more recording than there is (it says which scene and what to change).

## 1. What was recorded

1. **Which mods:** `mods` reads the loader's list from `latest.log` (Fabric/Quilt/Forge/NeoForge)
   or the mods folder. Without it, read the mod list menu, item tooltips, recipe (JEI/REI) screens
   and chat in the footage sheets.
2. **What happens:** open every `review/<video>/footage_*.png`; write a log of the recording with
   timecodes: "0:10-0:23 builds the portal", "0:24 lights it", "0:38-0:52 dark loading", "0:57 lava
   sea reveal". Make finer strips around key moments to pick exact in-points.
3. **What to cut:** menus and inventory, loading and black screens, standing still, walking with
   nothing new, repeats. Check suspicious dark stretches with a brightness measurement, not just by
   eye; QA flags black frames.

## 2. Research (accuracy gate)

Look every mod up on its official page (Modrinth, CurseForge, ContentDB, its repository) or read
its own files: real name, author, version, loader, features, recipes and licence. Note sources in
`research.md` and in each beat's `sources`. Never describe a feature you did not verify. If a
feature is not in the footage, show it on a card (list, comparison, fact), not over unrelated clips.

## 3. Script and structure (8-18 min for a real upload; median of small-channel hits is ~11 min)

Story beats work better than a feature list (data: "minecraft mods" scores 90/100, a dry
"mod showcase" only 29/100):
1. **Hook (0-20 s):** the most impressive or scary moment of the footage plus one line that
   promises what the video shows.
2. **What it is:** title card, mod name, version, loader (`chapter`).
3. **Getting started:** crafting or setup steps over the matching footage, with labels.
4. **The experience:** the features in the order you discover them, with your reactions; one beat
   per idea; funny fails are gold ("which is how I ended up taking a lava bath").
5. **Verdict:** `verdict` card (score, 2-4 pros, 1-3 cons) on cues, then a question for the comments.

Beats: 15-30 words. Footage beats use `{"template": "footage", "props": {"src", "in", "speed",
"zoom", "zoom_to", "focus", "label", "sublabel", "badge", "brightness"}}`. A clip needs
`scene length x speed` seconds of recording after `in`: do not reuse the same seconds in two beats,
and keep speed between 0.6 and 2 (slower looks choppy, faster hides what you explain). Use
`chapter` on the first beat of each section (at least 3; the first beat starts one).

## 4. Voice

`voice_engine`: `kokoro` (free, local, default; `voice` like `am_michael`) or `elevenlabs`
(`voice` = an ElevenLabs voice_id, key in `ELEVENLABS_API_KEY` in the environment, never in files
or chat; `voice_options` such as `{"stability": 0.45, "style": 0.3}`). `openai` also works with
`OPENAI_API_KEY`. Narration is cached per beat, so editing one beat re-voices only that beat.
Music: `hype` or `phonk` (beat, ducked under the voice) or an ambient mood.

## 5. Review and fix

Read `review/qa.md`, look at `overview.png` and every `sheet_*.png`: is the label readable and off
the action, does every clip show what the narration says, are any frames black or menus, are there
repeated shots? Fix the storyboard (in-points, speed, brightness, split a beat, turn a beat into a
card) and re-run `make`. Then check `out/description.md` and `out/thumbnail.png`.

## Rules

- Credit the mod author with a link to the official page in the description (`credits`); never
  link re-upload sites. Respect the mod licence.
- Honest opinions: no fake claims, no "best mod ever" without reasons. Disclose sponsorships.
- AI narration is fine on YouTube; do not clone a real person's voice without permission.
