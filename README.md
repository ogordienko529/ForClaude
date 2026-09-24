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
pytest                               # 80+ tests, no network needed
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
| `analyze_niche(query, format)` | Scored report (JSON + `summary_markdown`) | shorts ≈ 205, long ≈ 410, both ≈ 615 |
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

Each component is 0–100 and carries its raw numbers plus a one-line explanation. The final score is a weighted mean; weights live in `config.toml`:

| Component | Weight | What it measures |
|---|---:|---|
| Opportunity | 0.25 | Share of recent small-channel (<50k subs) uploads that reached the hit threshold (60%) + median outlier score (40%) |
| New-channel proof | 0.20 | Channels created in the last 12 months with a hit video (5+ = 100) |
| Velocity | 0.15 | Median views/day of typical uploads under 30 days old, log scale, per-format band |
| Consistency | 0.15 | Hits spread across many small channels, and a low share held by the single biggest hit |
| Competition | 0.10 | How little 100k+ channels dominate the top results (share of videos and of views) |
| Monetization | 0.15 | **ESTIMATE, not data**: RPM tier (low/medium/high) from query keywords, then video category. Shorts use a separate, much lower table |

Design choices worth knowing:

- **Two samples.** Each analysis runs a view-ordered search (what wins: outliers, competition) and a date-ordered search restricted to uploads at least 7 days old (what a *typical* upload gets: hit share, velocity). Using only view-ordered results would make every niche look great.
- **Direct 1–14 day evidence.** The API returns only current views, so `hit_within_14d` marks hits that are still ≤14 days old. Each refresh is stored as a snapshot, so repeat runs build a views-over-time history.
- **Shorts vs long-form.** A Short is ≤180 s **and** has a vertical embed (`part=player`, no extra cost). Horizontal clips under 3 min are excluded from Shorts stats. Long-form searches both the `medium` (4–20 min) and `long` (20+ min) buckets. Hit thresholds and velocity bands are configured separately per format, because Shorts views count every replay.
- **Two outlier scores.** `sub_outlier_score = views / max(subs, 100)` and `channel_relative_score = views / (channel views / video count)`. Shorts are ranked by the channel-relative score, long-form by the subscriber score.
- **Paid-promotion filter.** Long-form channels whose average views per video exceed 100× their subscriber count (typically ad-driven brand channels) are excluded from scoring and counted separately.
- **Language.** `relevanceLanguage` is only a hint to YouTube, so videos whose declared audio language differs are dropped and counted (`filter_by_audio_language`).
- **Low confidence.** Niches with fewer than 30 analysed videos or fewer than 5 small-channel hits are flagged.

The velocity bands were calibrated on a handful of real niches. Treat scores as a ranking aid, compare niches within the same format, and read the explanations.

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
