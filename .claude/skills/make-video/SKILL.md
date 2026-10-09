---
name: make-video
description: Make a narrated, animated explainer video entirely on this machine at zero cost (topic -> research -> storyboard -> voice -> music -> render -> self-review -> fixes). Use when the user asks to create a video, an explainer, a documentary episode or YouTube content.
---

# Make a video (local, $0)

You (Claude Code) are the writer, editor and reviewer. The `content_agent` CLI does the
mechanical work on this machine: Kokoro narration, procedural music, ffmpeg mix, Remotion
render in headless Chromium, and technical QA. No paid APIs, no uploads.

Default format: **animated explainer**, 16:9, 3-8 minutes, a calm documentary narrator, with maps,
timelines, stat counters, charts, kinetic text and fact cards. Shorts (9:16) are supported by
`--format shorts` but the templates are tuned for 16:9 first.

Commands (run from the repo root with the venv's Python):

```
python -m content_agent new <slug> --title "..."     # content_projects/<slug>/storyboard.json + research.md
python -m content_agent templates [--json]           # visual templates and their props
python -m content_agent validate <slug>              # L0 checks, must print OK
python -m content_agent make <slug>                  # voice -> music -> mix -> build -> render -> qa
python -m content_agent voice|music|mix|build|render|qa <slug>   # single steps
python -m content_agent still <slug> <scene> [--at 0.6]          # one PNG frame of a scene
python -m content_agent render <slug> --scene <id>               # one scene as a clip
```

## 1. Topic and angle

- If the user gave no topic, pick one with evidence: `python -m niche_core` reports (when a
  `YOUTUBE_API_KEY` is set) or the user's own channel data. State why the topic should work.
- Find the **angle**: one question the video answers ("Why did X stop?", "How did Y work?").
  The title promises it, the hook raises it in the first 15 seconds, the ending answers it.

## 2. Research (accuracy gate)

- Use web search. Put every fact you will say or show into `research.md` with its source URL.
- Numbers, dates and names need a source; key numbers need two independent ones. When sources
  disagree, use the safer wording (for example "less than two minutes" when sources say 70 s
  and 90 s) or the most authoritative source, and note the conflict in `research.md`.
- Prefer museums, official bodies, investigation reports and contemporary news over fan sites.
  Never invent quotes. Do not state anything you could not verify.

## 3. Storyboard

Edit `content_projects/<slug>/storyboard.json`. One beat = one scene = one idea.

- 15-30 words of narration per beat (validator limit: 4-45), so the picture changes every
  6-12 seconds. ~150 words = 1 minute. Split a beat when it has two ideas.
- Beat 1-2: the hook (a surprising concrete fact or question). Title card by beat 3.
- The visual must show what the narration says *at that moment*: places -> `map_route` /
  `map_point`, dates -> `timeline`, one number -> `stat`, two numbers -> `comparison`, several ->
  `bars`, reasons/steps -> `list`, a sourced claim -> `fact`, a punchline -> `kinetic`.
- Never the same template three times in a row; aim for 5+ different templates per video.
- **Sync reveals to the words** with `"cues"`: phrases copied from the narration, one per item
  (list items, bars, timeline events, comparison sides, kinetic lines; the first cue also starts a
  stat counter or map animation). Item *i* appears when cue *i* is spoken. Cues are matched in
  order; repeat a phrase to reveal several items together. Without cues, items are spread evenly.
  Example: narration "...Pan Am cancelled... the oil crisis... the noise..." with list items
  `["1973: Pan Am pulls out", "The oil crisis", "Noise and the sonic boom"]` ->
  `"cues": ["Pan Am", "oil crisis", "noise"]`.
- On-screen text is short (limits are enforced). Narration spells numbers out in words
  ("nineteen sixty-nine") so the voice reads them naturally; on-screen text uses digits.
- Every beat with facts lists its `sources`. End on the answer to the opening question.
- Palettes: midnight (default), parchment, slate. Music: calm, tense, uplifting, none.

Run `validate` until it prints OK and read the warnings.

## Visual style

`"style"` in the storyboard changes the whole look at once: fonts, colours, background, captions,
on-screen labels, scene transitions and motion. Run `python -m content_agent styles` to list them:
`cosmos` (dark stars, default), `paper` (documentary, typewriter captions), `blocky` (game look,
pixel font, tooltip captions, achievement toasts), `neon` (synthwave, karaoke captions, glitch
cuts), `clean` (bright minimal, big word-by-word captions) and `comic` (halftone, speech bubbles).

- Pick the style that suits the topic and audience: history or lore -> `paper` or `cosmos`; games
  and mods -> `blocky`; tech and sci-fi -> `neon`; tutorials and facts -> `clean`; funny -> `comic`.
- Keep one style for a series (viewers recognise it) and use a different style for each series, so
  the channel does not look mass-produced.
- A beat can override its entry with `"transition"` (fadePush, wipe, pixel, glitch, slide, zoomBurst,
  cut). Use it for emphasis, for example a glitch on a twist, not on every beat.
- Look at the contact sheets with the style's eyes: on `clean` and `comic` the background is bright,
  so dark footage needs labels, and the theme colours come from the style rather than `palette`.

## 4. Produce

`python -m content_agent make <slug>`. On a 4-core machine a 5-minute video takes about 2 min of
narration, under a minute of music and mixing, about 9 min of rendering and 2 min of QA.
Narration is cached per beat, so editing one beat only re-voices that beat.

## 5. Self-review (do not skip)

Look at the video the way a viewer would, using the review files:

1. Read `review/qa.md`: technical findings (loudness, silence, frozen or black frames, scene
   length, caption speed) keyed by scene id and timecode.
2. Open `review/overview.png` and every `review/sheet_*.png` with the Read tool (they are images:
   3 frames per scene, labelled with scene id, template and timecodes). Check every scene:
   text overflow or overlap, clipped labels, unreadable contrast, empty or half-built frames,
   map framing, wrong or misleading visuals, repeated looks.
3. Read `review/transcript.txt` against `research.md`: every claim correct and sourced?
4. Score the rubric printed in `qa.md` (hook, visual-narration match, readability, variety and
   pacing, accuracy, polish, audio) 1-5 and write `review/review.json`:
   `{"iteration": n, "scores": {...}, "findings": [{"scene": "b07", "severity": "high|medium|low", "problem": "...", "fix": "..."}]}`.

## 6. Fix loop

- Fix the cause, not the symptom: storyboard (wording, template choice, props) first; template
  code in `content_agent/remotion/src` only for real rendering bugs, and then check other scenes
  that use the same template.
- Re-run only what changed: narration edits -> `voice music mix build render`; visual-only edits
  -> `build render`. Check a single fixed scene first with `still` or `render --scene`.
- Re-run `qa` and review again. Done when there are no high or medium findings and every rubric
  score is at least 4, or after 3 iterations (then report what is left).

## 7. Hand-off

Give the user: the video path (`content_projects/<slug>/out/video.mp4`), length, a short summary,
the sources list, the final rubric scores and anything you could not fix. Nothing is published.

## Rules

- **Original work only.** Every video needs its own research, script and angle. Do not mass
  produce near-identical videos: YouTube demonetises repetitive or "inauthentic" content.
- Only use assets the pipeline generates or ships with a free licence: Natural Earth map data
  (public domain), Inter and Playfair Display fonts (OFL), procedural music. Do not download
  footage, images or music from the web into a project.
- Do not imitate a real person's voice or fabricate footage of real events.
- Never put API keys in files or commits; they come from environment variables.
