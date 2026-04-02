# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Run the server (Docker)
```bash
docker compose up --build       # foreground, with build
docker compose up --build -d    # background
docker compose logs -f          # follow logs
docker compose down             # stop
```

### Parse images to LaTeX
```bash
source .venv/bin/activate
cd parsing
python parse_notes.py "GLOB_PATTERN" [--model claude|gpt4o|gemini] [--output-dir ../tex_files/TOPIC/]
# Example:
python parse_notes.py "../handwritten/*.jpg" --model claude --output-dir ../tex_files/proj_geo/
```

### Add dependencies
```bash
source .venv/bin/activate && pip install <package>
```

`tectonic` (LaTeX compiler) is a system binary, not a pip package — install it separately before running the server.

## Architecture

Two independent subsystems connected by `tex_files/`:

```
handwritten/*.jpg
      │
      ▼
parsing/parse_notes.py  ──►  tex_files/TOPIC/*.tex  (body-only LaTeX)
      │                                │
  parsers/{claude,gpt4o,gemini}        ▼
                               server.py  ──► tectonic ──► PDF
```

**`parsing/`** — CLI batch converter. `parse_notes.py` globs images, instantiates the selected `BaseParser` subclass, and writes one `.tex` file per image. Output is **body-only** (no `\documentclass`, no `\begin{document}`) — preamble assembly is handled separately.

**`server.py`** — FastAPI server. `GET /pdf/{filename}` looks up `tex_files/{filename}.tex`, shells out to `tectonic` to compile it, and returns the PDF inline. The `render` endpoint is a placeholder.

## Key notes

- Parser implementations live in `parsing/parsers/`. The `PARSERS` dict in `__init__.py` maps CLI model names to classes.
- `ClaudeParser` loads `parsing/.claude.env` via `load_dotenv(".claude.env")` — must be run **from the `parsing/` directory**, not from the repo root.
- API keys: `SECRET_KEY` (Anthropic), `OPENAI_API_KEY` (OpenAI), `GOOGLE_API_KEY` (Google) — set in `.claude.env` or environment.
- `tex_files/` is organized by topic/notebook. Per-page body files are named after the source image (e.g. `Geo_Proye_1C2025_1.tex`). Assembled notebooks (e.g. `all_proj_geo.tex`) are edited manually.
