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

Two processes share a filesystem volume. The API writes job files; the worker consumes them.

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
workflow/worker.py  (poll loop)
     │  finds *.job in INBOX_DIR
     │  calls workflow/parsing → AI API → body-only LaTeX
     └► writes OUTPUT_DIR/{path}.tex
```

**`app/`** — FastAPI server.
- `main.py` — all HTTP endpoints. Reads env vars directly (`INBOX_DIR`, `OUTPUT_DIR`, `SECRET_TOKEN`).
- `latex.py` — `compile(tex_path)`: shells out to `tectonic` and returns PDF bytes. Called on demand by `GET /job/{path}.pdf`.

**`workflow/`** — background worker and AI parsers.
- `worker.py` — polls `INBOX_DIR` every 5 s for `*.job` files, calls `transcribe_images`, writes `.tex`.
- `parsing/__init__.py` — `transcribe_images(image_paths, model, fidelity)`. Exposes `MODEL_REGISTRY` (flat `model_id → class`) and `MODELS_BY_PROVIDER` (grouped, served by `GET /models`).
- `parsing/claude_parser.py` — Anthropic API. Uses `ANTHROPIC_API_KEY`.
- `parsing/gemini_parser.py` — Google Gemini via `google-genai`. Uses `GOOGLE_API_KEY`.
- `parsing/base.py` — `BaseParser` ABC, system prompt builder (`build_prompt(fidelity)`), fidelity blocks.

**`templates/`** — `index.html` (single-page UI), `master.tex.j2` (unused, kept for reference).

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

- Adding a new AI provider: add a parser class with a `MODELS: list[str]` attribute and `__init__(self, model: str, fidelity: str)` to `workflow/parsing/`, then register it in `workflow/parsing/__init__.py` (`MODELS_BY_PROVIDER` and `MODEL_REGISTRY`). The frontend and validation pick it up automatically.
- The worker derives the output subdirectory from the job file's position relative to `INBOX_DIR`, so `INBOX_DIR/foo/bar/01.job` produces `OUTPUT_DIR/foo/bar/01.tex`.
- LaTeX output is **body-only** (no `\documentclass`, no `\begin{document}`). The system prompt instructs the model to start with `\chapter`.
