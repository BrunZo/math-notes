# Notes Pipeline

A self-contained web service that accepts images of handwritten university notes, transcribes them to LaTeX via the Anthropic API, compiles the results with Tectonic, and serves the output as PDFs organized by course.

## Prerequisites

- [Docker](https://docs.docker.com/engine/install/) with the Compose plugin (`docker compose`)

## Setup

```bash
git clone ... && cd math-notes-viz
cp .env.example .env   # fill in SECRET_TOKEN and ANTHROPIC_API_KEY
```

## Running locally

```bash
docker compose up --build
```

The API is available at `http://localhost:8000`. Data is persisted in `/srv/notes` on the host (configurable via `NOTES_DIR` in your environment or `.env`).

To run in the background:

```bash
docker compose up --build -d
docker compose logs -f          # follow logs
docker compose down             # stop
```

## Deploying to the server

SSH into the server and run:

```bash
bash deploy.sh
```

See [`deploy.sh`](deploy.sh) for the `REPO_DIR` variable if your checkout is not at `~/code/math-notes-viz`.

## API usage

```bash
# Upload a lecture
curl -X POST http://localhost:8000/jobs \
  -H "Authorization: Bearer $SECRET_TOKEN" \
  -F "course_id=geo_proyectiva" \
  -F "course_name=Geometría Proyectiva" \
  -F "lecture_num=1" \
  -F "file=@clase1.jpg"

# Check job status
curl http://localhost:8000/jobs/{job_id} \
  -H "Authorization: Bearer $SECRET_TOKEN"

# Check all lectures for a course
curl http://localhost:8000/courses/geo_proyectiva/status \
  -H "Authorization: Bearer $SECRET_TOKEN"

# Download compiled course PDF
curl http://localhost:8000/courses/geo_proyectiva/pdf \
  -H "Authorization: Bearer $SECRET_TOKEN" \
  --output geo_proyectiva.pdf

# Health check (no auth required)
curl http://localhost:8000/health
```
