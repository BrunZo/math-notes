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
- `ingestion/parser.py` — parser worker: polls INBOX_DIR for `*.job` files, transcribes images and/or text inputs, writes `.tex` to PENDING_DIR.
- `ingestion/extractors.py` — text extraction by extension (`.txt`, `.md`, `.docx`, `.pdf` text layer) and PDF text-detection helper.
- `ingestion/config.py` — system prompt builder (`build_prompt(fidelity)`), fidelity blocks, `LATEX_CONSTRAINTS`.
- `testing/debugger.py` — compile + AI debug worker: polls PENDING_DIR for `*.tex`, moves to TEX_DIR or MANUAL_REVIEW_DIR. Configured via `DEBUG_MODEL` and `DEBUG_ITERS` env vars.
- `testing/config.py` — `DEBUG_SYSTEM_PROMPT` (includes preamble from `templates/load_preamble.py`).
- `repr/extractor.py` — metadata extraction worker (polls TEX_DIR for stale `.tex` files).
- `repr/expander.py` — CLI tool for expanding sections with AI.

**`llm/`** — AI client (single provider via OpenRouter).
- `openrouter.py` — `OpenRouterClient.send_prompt(model, prompt, media)` and `list_models()` (multimodal-only, fetched once per process from OpenRouter's `/models`). Uses `OPENROUTER_API_KEY`.

**`latex/`** — tectonic compilation (pure library, no worker logic).
- `compile.py` — `compile_single(tex_path)`, `compile_master(out_dir)`. Shells out to tectonic, returns PDF bytes.

**`templates/`** — `index.html` (single-page UI), `master.tex.j2` (LaTeX master document template), `load_preamble.py`, `course_full.html` (lecture viewer).

## Job file format

A `.job` file is JSON placed in `INBOX_DIR` by the API:

```json
{
  "model": "anthropic/claude-3.5-sonnet",
  "fidelity": "standard",
  "files": ["01_01.png", "01_02.txt", "01_03.docx"]
}
```

Files are listed relative to the job file's directory. Accepted extensions:
- Images (`.jpg`, `.jpeg`, `.png`, `.webp`) — sent multimodally.
- Text (`.txt`, `.md`, `.docx`, and `.pdf` whose text layer is non-trivial) — extracted at parse time and concatenated as text content.
- `.pdf` without an extractable text layer — rasterized to PNG pages at upload time.

Image and text inputs may be mixed in a single job.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_TOKEN` | yes | Bearer token for write endpoints |
| `OPENROUTER_API_KEY` | yes | OpenRouter API key (all AI calls go through it) |
| `NOTES_DIR` | yes | Root directory (contains inbox/, pending/, tex/, manual_review/) |
| `DEBUG_MODEL` | no | Model ID for the debugger's AI fix loop (empty = no AI debug) |
| `DEBUG_ITERS` | no | Max AI debug attempts per file (default: 3) |

## Key notes

- All models are accessed through OpenRouter. The available model list is fetched from OpenRouter at first use and cached per process — restart workers/API to pick up newly published models.
- The worker derives subdirectories from the job file's position relative to `INBOX_DIR`, so `INBOX_DIR/foo/bar/01.job` produces `PENDING_DIR/foo/bar/01.tex` and eventually `TEX_DIR/foo/bar/01.tex`.
- LaTeX output is **body-only** (no `\documentclass`, no `\begin{document}`). The system prompt instructs the model to start with `\chapter`.
