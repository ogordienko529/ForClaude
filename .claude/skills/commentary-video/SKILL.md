---
name: commentary-video
description: Edit a gameplay recording where the creator talked live while playing (horror, survival, challenge) into a long 16:9 video that keeps his real voice - find the reactions and the dead stretches, write cut.json (cold open + segments + chapters), render with voice and game on separate tracks, QA the opening, optionally dub the voice into English. Use when the user recorded with live commentary, or asks how to record so viewers play along with him.
---

# Long video from a live-commentary recording

The narrated review (script written and voiced after the session) loses most viewers in the first
minute on this channel: Verity 2 kept 46% at 0:30 and about 20% at 1:00, the Jerry long 0:52 of 4:13.
Viewers of horror and survival videos want to be *in the session* with the player: hear the panic when
it happens, not a calm story about it. Here the voice is the one recorded live, so the edit only cuts.

```
python -m content_agent footage <slug> D:\Videos\rec.mp4         # import + overview sheets (+ events)
python -m content_agent commentary <slug> footage/rec.mp4 [--transcribe]
                                                                 # reactions, dead stretches -> commentary/rec.md
python -m content_agent strip <slug> footage/rec.mp4 4015 --dur 20  # frames of one stretch (exact in/out)
python -m content_agent cut <slug> --draft                       # validate cut.json, render, QA (fast)
python -m content_agent cut <slug>                               # final render
python -m content_agent dub <slug> voice/dub_en.wav              # optional: English voice, same timing
```

MCP: `import_footage`, `commentary_analyze`, `footage_strip`, `run_step` with `cut_draft` / `cut`,
`read_qa`, `preview_frame`, `dub_mix`.

## 1. Recording (tell the creator before the session)

OBS, once:
- Settings → Output → Recording: Audio Track **1, 2, 3** ticked; Recording Format **MKV**
  (Settings → Advanced → "Automatically remux to MP4" on).
- Audio Mixer → ⚙ Advanced Audio Properties:
  - Mic: tracks 1 and 2;
  - game: add an **Application Audio Capture** source for `javaw.exe` (Minecraft), tracks 1 and 3;
  - Desktop Audio: track 1 only, or off (Discord and notifications must not reach tracks 2–3).
- Headphones, so the game does not leak into the mic. Mic peaks around −10 dB on the meter.

In the file: OBS track 1 = audio stream 0 (mix), track 2 = stream 1 (`voice_track: 1`),
track 3 = stream 2 (`game_track: 2`). With only one track set both to `null`: it still works, but
the game cannot be ducked under the voice and dubbing is impossible.

How to talk:
- Talk to the viewer, in the present tense: what you see, what you think it is, what you will do
  ("there's something in the trees... I'm not going in there... okay I'm going in").
- React out loud and do not hold back: the screams and laughs become the cold open and the Shorts.
- Never more than 3 seconds of silence while something is on screen; when nothing happens, say the
  plan or the fear.
- The first sentence of the session is the premise: "I installed a mod where my dog is not my dog."
- Language: English live is best. Ukrainian live is fine when English sounds stiff: dub it in
  section 5 (ElevenLabs dubbing keeps his intonation and timing, the clone keeps his timbre).

## 2. Find the moments

1. Open `review/<video>/overview_*.png` (one frame per 10 s) to know the story of the session.
2. Read `commentary/<video>.md`:
   - **Reactions**: voice jumps over his normal talking level (screams, laughs, shouts), with the
     size of the jump; the biggest are candidates for the cold open, chapter starts and Shorts;
   - **Dead stretches**: 8+ s with no talking and little motion: cut them;
   - **talking share**: under 40% means long silences; the edit will need more cuts.
   - With `--transcribe` (needs `pip install faster-whisper`, local and free) the timed transcript
     shows what he said: use it to cut on sentence ends and to write chapter names.
3. For every candidate, `strip` 10–20 s around it and find the exact in and out: start a segment
   on the sentence or action that sets the moment up, end it a beat after the payoff.

## 3. cut.json

```json
{"title": "My Dog Is Not My Dog Anymore",
 "voice_track": 1, "game_track": 2, "voice_gain_db": 0, "game_gain_db": -4, "duck_db": 6,
 "fps": 30, "height": 1080,
 "cold_open": [{"src": "footage/rec.mp4", "in": 4021.5, "out": 4026.0}],
 "segments": [
   {"id": "c01", "src": "footage/rec.mp4", "in": 12.0, "out": 47.5, "chapter": "The new dog"},
   {"id": "c02", "src": "footage/rec.mp4", "in": 63.0, "out": 118.0},
   {"id": "c03", "src": "footage/rec.mp4", "in": 310.5, "out": 371.0, "chapter": "Night one"}],
 "credits": [{"name": "Mod name", "author": "Author", "url": "https://modrinth.com/mod/..."}]}
```

Structure (retention rules, checked by QA where possible):
- **Cold open, 3–8 s**: the strongest reaction of the session, cut right after the payoff,
  no context. Then straight into the premise.
- **0:08–0:30**: his premise sentence, then play. No intro, no "hey guys", no subscribe ask, no
  title card. The first reaction must come by 0:30 (QA `first_reaction`).
- **Segments in session order**, each under 90 s (split longer ones by cutting the walking,
  inventory, menus and loading inside them). Something happens every 40–60 s.
- **No dead air over 2.5 s** (QA `dead_air`): trim the ends of segments to the speech.
- **Chapters**: on the segment where a new part of the story starts; at least 3, each 10 s or
  longer, the first one at 0:00 (the description writes it so).
- **Length**: what the good material carries. From 2–4 h of play that is usually 8–15 min; a tight
  8 min beats a padded 15.
- Keep the voice and picture together: never move a segment's audio, cut both.

## 4. Render and QA

`cut <slug> --draft`, then read `review/qa.md` and look at `review/first_frame.png`:
- `opening_voice`: no voice in the first 1.5 s; the cold open must start on sound;
- `first_reaction`: no reaction by 0:30; move one earlier or shorten the setup;
- `dead_air`: the timecodes to trim;
- technical checks (black frames, levels, duration).

Fix cut.json and run again until QA has no high findings. Then `cut <slug>` for the final file
(`out/video.mp4`, −14 LUFS) and check `out/description.md` (chapters, credits).

Studio targets after upload: 60%+ still watching at 0:30 (the narrated videos kept 46%),
average view duration over 35%.

## 5. Optional: English voice by dubbing

1. Upload `out/voice_stem.wav` (his voice only, already cut) to ElevenLabs Dubbing on the website,
   source Ukrainian, target English. On the website no API key is needed. Download the English voice
   track.
2. Save it to `content_projects/<slug>/voice/dub_en.wav` and run `dub <slug> voice/dub_en.wav`.
   It ducks the game under the new voice and writes `out/video_en.mp4` (upload this one) and
   `out/audio_original.m4a` (his Ukrainian track: add it in Studio → Languages → audio, if the
   channel has multi-language audio).
3. A note "padded or trimmed" means the dub is not the stem's length; check the end of the video.

## 6. Shorts from the same recording

The reactions list is the Shorts list. Use the `edit-gameplay` playbook (format `story`, 45–60 s,
or `moment`, 15–30 s) with `"game_audio": true`: it takes audio stream 0, the mix with his live
voice. Keep the music low (`volume_db` −14) or `"style": "none"` so the voice carries the Short.

## Rules

- Do not rewrite what he said: no synthetic voice over the live one, unless he asks (dubbing is his
  own voice translated).
- Do not cut inside a sentence unless the cut is the joke.
- Credit mod authors with official links only (Modrinth, CurseForge, the author's page).
