# Notes Pipeline

A self-contained web service that accepts images (or PDFs) of handwritten university notes, transcribes them to LaTeX via an AI model, and serves the compiled PDF on demand — a printer for handwritten notes.

## Prerequisites

- [Docker](https://docs.docker.com/engine/install/) with the Compose plugin (`docker compose`)

## Setup

```bash
git clone ... && cd math-notes-viz
cp .env.example .env   # fill in SECRET_TOKEN, ANTHROPIC_API_KEY, and/or GOOGLE_API_KEY
```

## Running

```bash
docker compose up --build       # foreground
docker compose up --build -d    # background
docker compose logs -f          # follow logs
docker compose down             # stop
```

The web interface is available at `http://localhost:8000`. Data is persisted under `/srv/notes` on the host (override with `NOTES_DIR` in your environment or `.env`).

## Usage

Open `http://localhost:8000` in a browser. The interface lets you:

1. **Submit a job** — give it a path (e.g. `topology/01`), choose a provider and model, pick a fidelity level, and upload images or a PDF.
2. **Track progress** — the Outputs table lists all jobs with their status (pending / done / error).
3. **Download results** — once done, download the `.tex` source or compile and download the `.pdf` directly from the table.

## API

All write endpoints require `Authorization: Bearer <SECRET_TOKEN>`. GET requests are unauthenticated.

```bash
# Submit a job
curl -X POST http://localhost:8000/job \
  -H "Authorization: Bearer $SECRET_TOKEN" \
  -F "path=topology/01" \
  -F "model=claude-opus-4-6" \
  -F "fidelity=standard" \
  -F "files=@lecture1.jpg"

# List all jobs and their status
curl http://localhost:8000/jobs

# Download the .tex output
curl http://localhost:8000/job/topology/01.tex --output 01.tex

# Compile and download as PDF (triggers tectonic on the server)
curl http://localhost:8000/job/topology/01.pdf --output 01.pdf

# List available models grouped by provider
curl http://localhost:8000/models

# Health check
curl http://localhost:8000/health
```

## Fidelity levels

| Level | Behaviour |
|---|---|
| `conservative` | Faithful transcription; fix only obvious errors |
| `standard` | Transcription with cleaned-up prose; expand abbreviations |
| `liberal` | Treat notes as an outline; produce a complete textbook section |
