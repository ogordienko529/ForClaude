# YouTube Niche Research

Find YouTube niches where **new or small channels** can realistically get **10,000+ views per video within the first 1–14 days**, for both Shorts and long-form, scored on earning potential as well as views.

It runs as a **CLI** (`python -m niche_core …`) and as an **MCP server** for Claude Code / Claude Desktop. It uses only the official YouTube Data API v3, with a local SQLite cache and quota tracking so you stay inside the free 10,000 units/day.

The repo also contains two local, free production tools: `sleep_voice` (natural sleep narration, [section 7](#7-sleep-narration-sleep_voice)) and `content_agent`, a video maker that Claude Code drives from topic to finished, self-reviewed video, and that also cuts raw gameplay into fast vertical Shorts ([section 8](#8-local-video-maker-content_agent)).

---

## 1. Get a YouTube API key (free, ~5 minutes)

1. Open <https://console.cloud.google.com/> and create a project (project picker at the top → **New Project**).
2. **APIs & Services → Library** → search **YouTube Data API v3** → **Enable**.
3. **APIs & Services → Credentials → Create credentials → API key**.
4. Restrict the key: under **API restrictions** choose **Restrict key** and tick only **YouTube Data API v3**. Leave **Application restrictions** at *None* (IP restrictions break on machines without a fixed IP).
5. Put the key in the environment variable `YOUTUBE_API_KEY`. The tool never reads it from files and never prints it:

   ```bash
   export YOUTUBE_API_KEY="AIza..."          # macOS / Linux (add to ~/.zshrc or ~/.bashrc)
   setx YOUTUBE_API_KEY "AIza..."            # Windows (new terminals)
   ```

No billing account is needed. When the daily quota runs out, requests are refused until midnight Pacific Time; nothing is charged.

## 2. Install

Requires Python 3.11+.

```bash
git clone <this repo> && cd ForClaude
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp config.example.toml config.toml   # optional: tweak thresholds, weights, bands
pytest                               # ~100 tests, no network needed
```

## 3. Use it from the command line

Every paid command prints its **estimated quota cost first** and asks for confirmation in an interactive terminal (`--yes` skips the prompt, `--dry-run` only prints the estimate, `--max-units N` refuses anything more expensive). After it runs, it prints the **actual** cost.

```bash
python -m niche_core quota                                          # units used today / remaining
python -m niche_core search "roman empire history" -f shorts        # raw recent videos
python -m niche_core outliers "history documentary" -f long --table # small channels that blew up
python -m niche_core analyze "history documentary" -f long --export # scored report (+ reports/*.md)
python -m niche_core expand "history documentary" -f long           # sub-niche ideas, 0 units if cached
python -m niche_core compare "aviation history" "cold war history" "mythology explained" -f long
python -m niche_core channels UCxxxxxxxxxxxxxxxxxxxxxx              # channel stats
python -m niche_core purge                                          # delete cached data older than retention
python -m niche_core backtest -f shorts --set all                   # calibration report (offline from cache)
```

Every search tool accepts `--region` (regionCode, default `US`) and `--lang` (relevanceLanguage, default `en`).

## 4. Register the MCP server

The server speaks stdio: `python -m niche_mcp` (or the `niche-mcp` script). Use **absolute paths**: the MCP client starts the server from an arbitrary working directory. If you use a `config.toml`, point `NICHE_CONFIG` at it and set `paths.reports_dir` to an absolute path in that file.

### Claude Code

```bash
claude mcp add --transport stdio --scope user youtube-niche \
  --env YOUTUBE_API_KEY=AIza... \
  --env NICHE_CONFIG=/absolute/path/to/ForClaude/config.toml \
  -- /absolute/path/to/ForClaude/.venv/bin/python -m niche_mcp
```

`--scope user` makes it available in every project; omit it to register it for the current project only. Check the registration with `claude mcp list`, or with `/mcp` inside Claude Code.

### Claude Desktop

Edit `claude_desktop_config.json`:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

(Settings → Developer → Edit Config opens it.)

```json
{
  "mcpServers": {
    "youtube-niche": {
      "command": "/absolute/path/to/ForClaude/.venv/bin/python",
      "args": ["-m", "niche_mcp"],
      "env": {
        "YOUTUBE_API_KEY": "AIza...",
        "NICHE_CONFIG": "/absolute/path/to/ForClaude/config.toml"
      }
    }
  }
}
```

On Windows the command is `C:\\path\\to\\ForClaude\\.venv\\Scripts\\python.exe`. Restart Claude Desktop after saving.

### Tools

| Tool | What it returns | Typical cost (uncached) |
|---|---|---|
| `search_niche(query, format, published_within_days=30, max_results=50)` | Recent videos: views, likes, comments, duration, publish date, channel id | 100 per duration bucket + 1 per 50 videos |
| `get_channel_stats(channel_ids)` | Subscribers (None if hidden), total views, video count, created date, avg views/video | 1 per 50 channels |
| `find_outliers(query, format, min_outlier_score=10, max_channel_subs=50000)` | Small-channel videos far above their channel's size, with both outlier scores | ≈ search + 2–4 |
| `analyze_niche(query, format)` | Forecast + view score (with 80% ranges) + final score, components, top outliers (JSON + `summary_markdown`) | shorts ≈ 205, long ≈ 410, both ≈ 615 |
| `compare_niches(queries, format)` | Ranked markdown table (`table_markdown`) + per-niche scores | sum of analyze_niche |
| `expand_keywords(seed)` | Sub-niche queries from outlier titles/tags | 0 if seed cached, else find_outliers once |
| `quota_status()` | Units used today, remaining, per-endpoint breakdown | 0 |

Every tool accepts `dry_run` (estimate only) and `max_units` (refuse if the estimate is higher). Every result carries `quota: {estimated, actual, used_today, remaining}`. Search tools accept `region_code` and `relevance_language`.

### Example prompts for Claude

- "Check my YouTube quota, then find Shorts outliers for *roman empire history* from channels under 20k subs."
- "Expand the seed *history documentary* into sub-niches, then compare the 5 most promising ones for long-form. Do a dry run first and tell me the cost."
- "Analyze *aviation history* for both formats and export the report. Which format should a brand-new channel pick, and why?"
- "Compare *personal finance for teens*, *budget travel japan* and *cozy cooking* as Shorts in region GB."
- "Show me the top 10 outlier videos in *mythology explained* and what their titles have in common."

## 5. How niches are scored

Every analysis returns three things:

1. **Forecast:** the chance that a typical upload from a small channel (≤ 50k subs) reaches 10,000
   views in its first 1–3 weeks, with an 80% range. It uses the niche's recent uploads, shrunk
   toward the panel average when the sample is small, and widened by how much niches drift month
   to month.
2. **View score (0–100)** with an 80% range (bootstrap): how good the niche is for views.
3. **Final score** = 0.85 × view score + 0.15 × monetization ESTIMATE. Both weights are in `config.toml`.

View-score components (each 0–100, with raw numbers and a one-line explanation):

| Component | What it measures | Weight: Shorts | Weight: long |
|---|---|---:|---:|
| Opportunity | Share of typical small-channel uploads that reached 10k (shrunk), plus median views of small channels in the top results | 0.35 | 0.50 |
| Demand | Median views of the top results: how much audience the topic pulls | 0.30 | 0.50 |
| New-channel proof | Channels under 12 months old with a 10k+ video, plus their hit rate | 0.15 | 0 |
| Velocity | Median views/day of a typical upload | 0.10 | 0 |
| Consistency | Hits spread across many small channels rather than one lucky video | 0.10 | 0 |
| Competition | Share of top results and views taken by 100k+ channels (reported, not weighted) | 0 | 0 |
| Monetization | **ESTIMATE, not data**: RPM tier from query keywords, then category; separate Shorts table | final score only | final score only |

### How we know it works

The weights are not guesses. `python -m niche_core backtest` runs a temporal backtest: a score
computed on uploads 60–30 days old is checked against what small channels actually got 21–7 days
ago (`docs/CALIBRATION.md`, criteria in `docs/QUALITY_CRITERIA.md`):

- **Shorts:** ranking ρ 0.78 on 11 niches the model had never seen.
- **Long-form:** ρ 0.83, leave-one-out, over 14 niches.
- **Long-form forecasts** are off by 4–6 percentage points on average.
- **Shorts forecasts** are much wider, because Shorts niches swing ±30 pp from month to month.

Findings that shaped the design:

- **Big channels in a niche signal demand, not a barrier.** "Fewer big channels = better" had the
  wrong sign in both formats, so competition is shown but not penalised.
- **Long-form hits are mostly over 20 minutes (63–74%).** Long-form therefore searches both the
  4–20 min and 20+ min buckets.
- **Ad-driven views are filtered by engagement.** Near-zero likes and comments on a huge view
  count mark them (a brand video had 0 likes on 3.6M views); organic hits sit at 0.2–3% likes.

Other design choices:

- **Shorts vs long-form.** A Short is ≤ 180 s **and** has a vertical embed (`part=player`, no extra
  cost). Horizontal clips under 3 minutes are excluded. Bands are set per format, because Shorts
  views count every replay.
- **Two outlier scores** in `find_outliers`: `views / max(subs, 100)` and `views / channel average`.
- **Language.** `relevanceLanguage` is only a hint, so videos whose declared audio language differs
  are dropped and counted.

Re-run the backtest on your own niches with `python -m niche_core backtest -f long --queries "..." --collect`.
After collecting, calibration iterations run offline for free.

## 6. Quota, cache and data retention

- Costs: `search.list` = 100 units, `videos.list` / `channels.list` = 1 unit per call (batched 50 IDs). The daily limit is 10,000 and resets at midnight Pacific Time; usage is tracked per Pacific day in the database.
- Cache TTLs: videos and searches 24 h, channels 7 days. A fresh cache hit costs 0.
- **Data retention:** the YouTube API policies require stored API data to be refreshed or deleted within 30 days. Rows older than `retention_days` (default 30, max 30; enforced at config load) are deleted on every startup and by `python -m niche_core purge`.
- Errors: `quotaExceeded` stops the run and returns partial results (`partial: true`). 5xx and rate-limit errors are retried up to 3 times with backoff. If the API fails, older cached data within retention is used and reported under `errors`. Hidden subscriber counts and disabled likes or comments are `null`, never 0, and are counted under `data_quality`.

## 7. Sleep narration: `sleep_voice`

Turns a script into a calm, natural English male voice-over for sleep documentaries, with
subtitles and YouTube chapters. It runs locally and free, with no API key: Kokoro-82M TTS
(Apache-2.0 licence, so commercial and monetized use is allowed) plus a sleep-specific
processing chain.

```bash
pip install -e ".[voice]"            # + ffmpeg: brew install ffmpeg / winget install ffmpeg / apt install ffmpeg
python -m sleep_voice voices          # list male voices
python -m sleep_voice samples -o voice_samples     # 45-second demo of each voice and two blends
python -m sleep_voice estimate script.txt          # how long it will be (~6,300 words per hour)
python -m sleep_voice render script.txt -o episode.mp3 --voice am_michael --background brown
```

`render` writes `episode.mp3`, `episode.srt` (upload it as captions) and `episode.chapters.txt`
(paste it into the description to get YouTube chapters). The model (~350 MB) downloads once on
first use.

**What makes it sleep-friendly:**

- **Pace:** it starts slower than normal reading (speed 0.88) and eases down to 0.80 over the
  episode (the wind-down). Pauses grow by about 35% along the way.
- **Pauses:** sentence 0.85 s, paragraph 2 s, chapter 4.5 s, each with ±15% natural variation.
  `[pause 5s]` in the script inserts exact silence.
- **No jolts:** exclamation marks become full stops, SHOUTED words are lowered, emoji are removed,
  and every sentence is matched to the same loudness.
- **Softer, warmer tone:** a 9 kHz low-pass, +2 dB warmth at 180 Hz, −3 dB presence at 3.5 kHz,
  a de-esser and a gentle compressor.
- **Quiet and even:** −20 LUFS (YouTube plays most content at −14), true peak ≤ −3 dB.
- **Optional bed:** brown or pink noise, or your own rain file, far below the voice (`--background`,
  `--background-db`).
- **Correct reading of documentary text:** 1888 → "eighteen eighty-eight", 1950s → "nineteen
  fifties", $20 → "twenty dollars", −40°C, Dr./St./Mr., WWII, 9/11, km, % and clock times.
  Fix any other word with `--lexicon lexicon.toml` (`Meteora = "Meh-teh-OR-ah"`).
- **Resumable:** every sentence is cached, so a crashed 3-hour render resumes, and editing one
  paragraph re-synthesises only that paragraph.

**Script format:** plain text. A blank line starts a new paragraph, `# Title` starts a chapter, and
`[pause 5s]` inserts silence. See `examples/lighthouse_sleep_demo.txt`.

**Engines** (`--engine`), from free to most natural:

| Engine | Naturalness | Cost | Needs |
|---|---|---|---|
| `kokoro` (default) | good; best of the light models | free | CPU |
| `chatterbox` | very natural (preferred over ElevenLabs in 63% of blind tests); can clone a reference voice | free (MIT) | `pip install chatterbox-tts`; a GPU is strongly advised |
| `openai` | very natural; style is set in plain English (`--instructions`) | ≈ $0.015/min, about $2 for 2 hours | `OPENAI_API_KEY`; voices `onyx`, `ash`, `cedar`, `echo`, `sage` |
| `elevenlabs` | the benchmark | ≈ $0.10–0.20/min | `ELEVENLABS_API_KEY`, `--voice <voice_id>` |

```bash
python -m sleep_voice render script.txt -o ep.mp3 --engine openai --voice onyx
python -m sleep_voice render script.txt -o ep.mp3 --engine chatterbox --voice my_calm_voice.wav --exaggeration 0.3 --cfg-weight 0.35
python -m sleep_voice samples --engine openai -o samples_openai     # compare OpenAI voices
```

By default, every engine speaks **whole paragraphs** (`--unit paragraph`), so intonation flows like a
person reading instead of resetting at each sentence. The pauses between sentences are then stretched
to the sleep pacing, while short comma pauses are left alone. Use `--unit sentence` for the old behaviour.
Only clone a voice you have the rights to, such as your own.

**Voices:** `am_michael` (warm, steady; the default), `am_onyx` (deep), `bm_george` (British,
classic documentary) and `bm_lewis` (British, deep and slow). You can also blend voices into a
timbre of your own that stays consistent across videos, e.g. `--voice am_michael:0.6,bm_george:0.4`.

**Presets:** `--preset sleep` (default), `deep` (slower, quieter, darker) and `calm` (for pre-sleep
documentaries).

**Speed:** about 20 s of CPU per minute of audio on 4 cores, so a 2-hour episode takes about 40 minutes.

**YouTube note:** AI narration is allowed and a narration voice does not need the "altered or
synthetic" label. Monetization reviews do reject mass-produced, repetitive channels, though, so
original, researched scripts matter more than the voice.

## 8. Local video maker: `content_agent`

Makes a narrated, animated explainer video **on your own computer for $0**: no paid APIs, no
uploads. Claude Code is the writer, editor and reviewer (it follows the playbook in
`.claude/skills/make-video/SKILL.md`). The `content_agent` CLI does the mechanical work:

| Step | Tool (all local, free) |
|---|---|
| Research, script, storyboard | Claude Code + web search, sources kept in `research.md` |
| Narration | Kokoro via `sleep_voice` (documentary pacing, cached per scene) |
| Music | procedural ambient pads generated with numpy: no licence or Content ID risk |
| Mix | ffmpeg: voice clean-up, music ducked under the voice, −14 LUFS |
| Picture | Remotion (React) templates rendered in headless Chromium |
| Self-review | ffmpeg checks + contact sheets that Claude Code looks at, fixes by scene id |

```bash
pip install -e ".[agent]"     # + ffmpeg and Node.js 18+ (the renderer installs its npm packages on first run)
python -m content_agent new concorde --title "Why Concorde Stopped Flying"
python -m content_agent templates            # what each visual template needs
# write content_projects/concorde/storyboard.json (or ask Claude Code: "make a video about ...")
python -m content_agent validate concorde
python -m content_agent make concorde        # voice -> music -> mix -> timeline -> render -> QA
```

The result is `content_projects/<name>/out/video.mp4`. The review material is in `review/`:
`qa.md` (technical findings with scene ids and timecodes), `overview.png` and `sheet_*.png`
(three frames of every scene), and `transcript.txt`.

**The storyboard is the single source of the video.** Each beat has narration, a visual template
with its props, and sources. Everything else is derived from it, so a fix touches one beat:
`still <name> <scene>` previews one frame and `render <name> --scene <id>` renders one scene.
Optional `cues` (phrases from the narration) make each list item, bar, timeline event or line of
text appear at the moment the narrator says it.
An example is in `examples/content/concorde/`.

**Visual templates:** `title`, `kinetic` (animated text), `map_route` (great-circle route with a
plane or ship), `map_point` (zoom to a place), `timeline`, `stat` (counter), `comparison`, `bars`,
`fact` (sourced quote or fact card), `list`. There are three palettes (midnight, parchment and slate)
and music moods calm, tense and uplifting. The map is Natural Earth (public domain) and the fonts
are Inter and Playfair Display (OFL), all bundled, so rendering works offline.

**Checks:** before rendering, the storyboard is checked for unknown templates, missing props, text
too long for the screen, missing sources and repetitive visuals. After rendering, the video is
checked for loudness and true peak, silences, black or frozen frames, scenes that are too long or
too short, and caption reading speed. Claude Code then reviews the contact sheets against a
7-point rubric (hook, visual–narration match, readability, variety, accuracy, polish, audio) and
fixes until no serious finding is left.

**Speed** on a 4-core machine, for the 5-minute demo: narration 2 min, music and mix under
1 min, rendering about 9 min (1.7x the video length) and QA about 2 min.

**Licences:** Remotion is free for individuals and companies with up to 3 employees (a company
licence is needed above that). Kokoro is Apache-2.0.

### Fast gameplay edits (no voice-over, 9:16)

The second mode turns a raw gameplay recording (Minecraft and similar) into a fast vertical Short.
Claude Code follows `.claude/skills/edit-gameplay/SKILL.md`: it looks at footage sheets, finds the
payoff to the exact frame and writes `edit.json`, a list of segments measured in beats, with speed,
crop or fit framing, punch-ins and push-ins, shake, flash, black-and-white freeze frames, meme text
and SFX. The build step generates a phonk/hype beat whose drop lands on the payoff (with a
tape-stop on the freeze frame), mixes the SFX to -14 LUFS, and renders 1080x1920.

```bash
python -m content_agent footage mc_tnt raw_gameplay.mp4    # analyse: motion, bursts, idle parts + footage sheets
python -m content_agent make mc_tnt                        # validate -> soundtrack -> render -> QA (pacing, hook)
```

QA adds fast-edit rules: text on screen within 0.5 s, nothing static for more than 2.2 s, and a
total length of 10-60 s. The niche data, the editing playbook and the demo are in
[`docs/GAMEPLAY_EDITING.md`](docs/GAMEPLAY_EDITING.md). The demo footage was recorded in Luanti (an
open-source voxel game) by `examples/gameplay_sim/record.py`, because Minecraft cannot run in a
server container. The script uses real keyboard and mouse input on a virtual display, and needs
`apt install minetest xvfb xdotool` and `pip install python-xlib`.

## 9. Project layout

```
niche_core/          core library (all logic) + CLI (__main__.py)
  youtube_client.py  API calls, batching, retries, quota metering
  cache.py           SQLite: videos, snapshots, channels, searches, quota_log; purge
  quota.py           Pacific-day usage, estimates
  enrich.py          outlier metrics (pure)
  scoring.py         niche scoring (pure)
  patterns.py        title patterns, keyword expansion
  rpm.py             monetization ESTIMATE tables
  report.py          insights, markdown, export
  service.py         the 7 operations + purge
niche_mcp/server.py  thin MCP wrapper
sleep_voice/         sleep narration: text normalisation, Kokoro TTS, pacing, mastering, SRT/chapters
content_agent/       local video maker: storyboard checks, voice/music/mix, timeline, QA, CLI
  gameplay.py        fast gameplay edits: footage analysis, edit.json, soundtrack, timeline
  sound.py           procedural beat music (drop, tape-stop) and sound effects
  remotion/          React video templates (maps, timelines, stats, text) rendered by Remotion
.claude/skills/      make-video and edit-gameplay playbooks that Claude Code follows
tests/               fixture-based tests (no network)
config.example.toml  every tunable, documented
```
