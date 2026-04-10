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
     │  GET  /job/{path}.tex  ←  OUTPUT_DIR/{path}.tex
     │  GET  /job/{path}.pdf  ←  OUTPUT_DIR/{path}.tex  →  tectonic  →  PDF bytes
     │  GET  /jobs            ←  scans OUTPUT_DIR + INBOX_DIR
     │
     ▼ (shared volume)
workflow/ingestion/parser.py  (poll loop)
     │  finds *.job in INBOX_DIR
     │  calls workflow/ingestion/parsing → AI API → body-only LaTeX
     └► writes OUTPUT_DIR/{path}.tex + .tex.job signal
         │
workflow/latex/compiler.py  (poll loop)
     │  finds *.tex.job in OUTPUT_DIR
     │  compiles with tectonic → success or .bug
         │
workflow/latex/debugger.py  (poll loop)
     │  finds *.bug in OUTPUT_DIR/bugs
     │  AI-based fix → re-signals compiler
         │
workflow/extractor.py  (poll loop)
         finds stale *.tex in OUTPUT_DIR
         extracts metadata → .meta.json + index.json
```

**`app/`** — FastAPI server.
- `main.py` — all HTTP endpoints. Reads env vars directly (`SECRET_TOKEN`). Imports paths from `config/paths.py`.

**`workflow/`** — background workers and AI parsers.
- `base.py` — generic `Worker` dataclass (poll loop), `glob_finder`, `setup_logging`.
- `ingestion/parser.py` — parser worker: polls INBOX_DIR for `*.job` files, calls `transcribe_images`, writes `.tex`.
- `ingestion/parsing/__init__.py` — `transcribe_images(image_paths, model, fidelity)`. Exposes `MODEL_REGISTRY` (flat `model_id → class`) and `MODELS_BY_PROVIDER` (grouped, served by `GET /models`).
- `ingestion/parsing/claude_parser.py` — Anthropic API. Uses `ANTHROPIC_API_KEY`.
- `ingestion/parsing/gemini_parser.py` — Google Gemini via `google-genai`. Uses `GOOGLE_API_KEY`.
- `ingestion/parsing/base.py` — `BaseParser` ABC, system prompt builder (`build_prompt(fidelity)`), fidelity blocks, `LATEX_CONSTRAINTS`.
- `testing/compiler.py` — compiler worker (polls for `*.tex.job`, calls `latex.compile`).
- `testing/debugger.py` — AI-based LaTeX error fixing worker (polls for `*.bug`).

**`latex/`** — tectonic compilation (pure library, no worker logic).
- `compile.py` — `compile(tex_path)`, `compile_single(tex_path)`, `compile_master(out_dir)`. Shells out to tectonic, returns PDF bytes.
- `extractor.py` — metadata extraction worker (polls for stale `.tex` files).
- `expand.py` — CLI tool for expanding sections with AI.

**`templates/`** — `index.html` (single-page UI), `master.tex.j2` (LaTeX master document template), `course_full.html` (lecture viewer).

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
| `INBOX_DIR` | yes | Directory the worker polls for `.job` files |
| `OUTPUT_DIR` | yes | Directory where `.tex` and `.error` files are written |

## Key notes

- Adding a new AI provider: add a parser class with a `MODELS: list[str]` attribute and `__init__(self, model: str, fidelity: str)` to `workflow/ingestion/parsing/`, then register it in `workflow/ingestion/parsing/__init__.py` (`MODELS_BY_PROVIDER` and `MODEL_REGISTRY`). The frontend and validation pick it up automatically.
- The worker derives the output subdirectory from the job file's position relative to `INBOX_DIR`, so `INBOX_DIR/foo/bar/01.job` produces `OUTPUT_DIR/foo/bar/01.tex`.
- LaTeX output is **body-only** (no `\documentclass`, no `\begin{document}`). The system prompt instructs the model to start with `\chapter`.
