# ForClaude

Tools for a YouTube creator, all run locally. The user speaks Ukrainian: reply in Ukrainian, keep
video narration and on-screen text in English unless told otherwise. The user prefers action over
questions ("не запитуй, а роби").

## What is here

| Tool | What it does | Entry point | Docs |
|---|---|---|---|
| `niche_core` | YouTube niche research: small channels that blew up, niche scores, RPM estimates | `python -m niche_core …` | README sections 3–6 |
| `niche_mcp` | the same as an MCP server (stdio) | `python -m niche_mcp` | README section 4 |
| `sleep_voice` | long, calm sleep narration (Kokoro TTS, free) | `python -m sleep_voice …` | README section 7 |
| `content_agent` | video maker: narrated explainers, fast gameplay Shorts, mod reviews | `python -m content_agent …` | README section 8, `docs/CONTENT_AGENT.md`, `docs/GAMEPLAY_EDITING.md` |

**content-maker** is the autonomous producer on top of `content_agent`:
- **Director prompt:** `.claude/agents/content-maker.md`.
- **Tools:** the MCP server `python -m content_agent mcp` (project state, footage import, mod
  detection, validation, pipeline steps as background jobs, frame previews, QA report, doctor).
- **Run it unattended:** `python -m content_agent agent "<task>" --files ...`. Continue with
  `--resume "<answer>"`, stop for plan approval with `--plan`, chat with `-i`.
- **Options before production:**
  - `python -m content_agent ideas "<theme>"` proposes video ideas backed by data;
  - `agent --options --files rec.mp4` proposes edit variants of a recording;
  - the user picks with `agent --pick N`;
  - proposals are saved in `content_projects/.agent/options/`;
  - `content_projects/channel.md` (optional, template in `examples/channel.example.md`) describes
    the channel for better ideas.
- **Hand over a whole video:** when the user asks for one, delegate it to the `content-maker`
  subagent (or run the command above).
- **Machine checks:** `python -m content_agent doctor`. One-time setup:
  `python -m content_agent setup`.

Playbooks in `.claude/skills/` (follow them when the request matches):
- `make-video`: topic → narrated animated explainer.
- `edit-gameplay`: raw gameplay → fast vertical Short, no voice.
- `review-video`: silent mod recording → narrated mod review with chapters, verdict, thumbnail.

When the user brings footage together with a shooting script, put both in `content_projects/<slug>/`
and edit the footage to the script with the `review-video` playbook.

## Setup (once per machine)

Needs Python 3.11+, ffmpeg and Node.js 18+ on PATH.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,agent]"
python -m content_agent setup  # renderer packages, Kokoro model, MCP registration, then doctor
pytest -q                      # offline, should be all green
```

- Install ffmpeg and Node.js:
  - Windows: `winget install Gyan.FFmpeg` and `winget install OpenJS.NodeJS.LTS`, then open a new
    terminal;
  - macOS: `brew install ffmpeg node`;
  - Linux: `apt install ffmpeg nodejs npm`.
- On first use, these download automatically:
  - the Kokoro voice model (~340 MB, into `~/.sleep_voice/models`);
  - the Remotion npm packages and its headless Chrome.

Always run the tools with the venv's Python (`.venv\Scripts\python` on Windows, `.venv/bin/python`
elsewhere) or with the venv activated.

## Secrets: never in files, never in commits

The repo is public.
- `YOUTUBE_API_KEY`: niche research.
- `ELEVENLABS_API_KEY`: ElevenLabs voices.
- `OPENAI_API_KEY`: OpenAI voices.

Read all of these from environment variables only. Never ask the user to paste a key into the chat,
and never write one to a file. If one is missing, tell the user how to set it:
- Windows: `setx NAME "value"`, then a new terminal;
- macOS/Linux: `export NAME=...` in the shell profile.

## Working rules

- Niche research spends the daily YouTube quota (10,000 units):
  - check `python -m niche_core quota` first;
  - the commands print a cost estimate; pass `--yes` to skip the confirmation prompt.
- Video projects live in `content_projects/<slug>/`. The folder is gitignored and holds footage and
  renders. Do not commit it.
- `content_agent` pipeline: `storyboard.json` (long-form) or `edit.json` (Shorts) →
  `validate` → `make` → look at the QA contact sheets → fix by scene id → re-render.
- Run `pytest -q` after code changes.
