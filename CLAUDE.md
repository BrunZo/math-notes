# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Run the service (Docker)
```bash
docker compose up --build       # foreground, with build
docker compose up --build -d    # background
docker compose logs -f          # follow logs
docker compose down             # stop
```

### Add dependencies
```bash
pip install <package>           # then add to requirements.txt
```

`tectonic` (LaTeX compiler) is installed inside the Docker image — it is not a pip package.

## Architecture

Multiple worker processes share a filesystem volume. The API writes job files; workers consume them.

```
Browser / curl
     │
     ▼
app/main.py  (FastAPI)
     │  POST /job  →  INBOX_DIR/{path}.job  +  images
     │  GET  /job/{path}.tex  ←  TEX_DIR/{path}.tex
     │  GET  /job/{path}.pdf  ←  TEX_DIR/{path}.tex  →  tectonic  →  PDF bytes
     │  GET  /jobs            ←  scans TEX_DIR + PENDING_DIR + INBOX_DIR
     │
     ▼ (shared volume)
workflow/ingestion/parser.py  (poll loop)
     │  finds *.job in INBOX_DIR
     │  AI API → body-only LaTeX
     └► writes PENDING_DIR/{path}.tex
         │
workflow/testing/debugger.py  (poll loop)
     │  finds *.tex in PENDING_DIR
     │  compiles with tectonic + AI debug loop
     └► success → TEX_DIR/{path}.tex
        failure → MANUAL_REVIEW_DIR/{path}.tex
         │
workflow/repr/extractor.py  (poll loop)
         finds stale *.tex in TEX_DIR
         extracts metadata → SQLite IR
```

**`app/`** — FastAPI server.
- `main.py` — all HTTP endpoints. Reads env vars directly (`SECRET_TOKEN`). Imports paths from `config/paths.py`.

**`workflow/`** — background workers and AI parsers.
- `base.py` — generic `Worker` dataclass (poll loop), `setup_logging`.
- `utils.py` — shared helpers (`glob_finder`, `stale_tex_finder`).
- `ingestion/parser.py` — parser worker: polls INBOX_DIR for `*.job` files, transcribes images, writes `.tex` to PENDING_DIR.
- `ingestion/config.py` — system prompt builder (`build_prompt(fidelity)`), fidelity blocks, `LATEX_CONSTRAINTS`.
- `testing/debugger.py` — compile + AI debug worker: polls PENDING_DIR for `*.tex`, moves to TEX_DIR or MANUAL_REVIEW_DIR. Configured via `DEBUG_MODEL` and `DEBUG_ITERS` env vars.
- `testing/config.py` — `DEBUG_SYSTEM_PROMPT` (includes preamble from `templates/load_preamble.py`).
- `repr/extractor.py` — metadata extraction worker (polls TEX_DIR for stale `.tex` files).
- `repr/expander.py` — CLI tool for expanding sections with AI.

**`llm/`** — AI client abstraction.
- `base.py` — `BaseAIClient` ABC.
- `claude.py` — Anthropic API client. Uses `ANTHROPIC_API_KEY`.
- `gemini.py` — Google Gemini client. Uses `GOOGLE_API_KEY`.
- `__init__.py` — `MODEL_REGISTRY` (flat `model_id → class`) and `MODELS_BY_PROVIDER`.

**`latex/`** — tectonic compilation (pure library, no worker logic).
- `compile.py` — `compile_single(tex_path)`, `compile_master(out_dir)`. Shells out to tectonic, returns PDF bytes.

**`templates/`** — `index.html` (single-page UI), `master.tex.j2` (LaTeX master document template), `load_preamble.py`, `course_full.html` (lecture viewer).

## Job file format

A `.job` file is JSON placed in `INBOX_DIR` by the API:

```json
{
  "model": "claude-opus-4-6",
  "fidelity": "standard",
  "images": ["01_01.png", "01_02.png"]
}
```

Images are listed relative to the job file's directory.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_TOKEN` | yes | Bearer token for write endpoints |
| `ANTHROPIC_API_KEY` | for Claude | Anthropic API key |
| `GOOGLE_API_KEY` | for Gemini | Google API key |
| `NOTES_DIR` | yes | Root directory (contains inbox/, pending/, tex/, manual_review/) |
| `DEBUG_MODEL` | no | Model ID for the debugger's AI fix loop (empty = no AI debug) |
| `DEBUG_ITERS` | no | Max AI debug attempts per file (default: 3) |

## Key notes

- Adding a new AI provider: add a client class extending `BaseAIClient` with a `MODELS: list[str]` attribute to `llm/`, then register it in `llm/__init__.py`. The frontend and validation pick it up automatically.
- The worker derives subdirectories from the job file's position relative to `INBOX_DIR`, so `INBOX_DIR/foo/bar/01.job` produces `PENDING_DIR/foo/bar/01.tex` and eventually `TEX_DIR/foo/bar/01.tex`.
- LaTeX output is **body-only** (no `\documentclass`, no `\begin{document}`). The system prompt instructs the model to start with `\chapter`.
