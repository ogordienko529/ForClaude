# YouTube Niche Research

Find YouTube niches where **new or small channels** can realistically get **10,000+ views per video within the first 1–14 days**, for both Shorts and long-form, scored on earning potential as well as views.

It runs as a **CLI** (`python -m niche_core …`) and as an **MCP server** for Claude Code / Claude Desktop. It uses only the official YouTube Data API v3, with a local SQLite cache and quota tracking so you stay inside the free 10,000 units/day.

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

## 7. Project layout

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
tests/               fixture-based tests (no network)
config.example.toml  every tunable, documented
```
