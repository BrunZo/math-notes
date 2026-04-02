# Notes Pipeline

A self-contained web service that accepts images of handwritten university notes, transcribes them to LaTeX via the Anthropic API, compiles the results with Tectonic, and serves the output as PDFs organized by course.

## System dependencies

Install these before anything else:

**Tectonic** (LaTeX compiler):
```bash
curl --proto '=https' --tlsv1.2 -fsSL https://drop.xz.tools/install.sh | sh
```

**Python 3.12** (via deadsnakes PPA if not present):
```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update && sudo apt install python3.12 python3.12-venv
```

## Setup

```bash
git clone ... && cd notes-pipeline
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in values
sudo mkdir -p /srv/notes/{inbox,output,.tectonic-cache}
sudo chown -R ubuntu:ubuntu /srv/notes
python -c "from app.db import init_db; init_db()"
```

## Running locally

Open two terminals:

```bash
# Terminal 1 — API server
source .venv/bin/activate
uvicorn app.main:app --reload

# Terminal 2 — Worker
source .venv/bin/activate
python -m app.worker
```

## Deploying with systemd

```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now notes-api notes-worker
```

View logs:
```bash
journalctl -u notes-api -f
journalctl -u notes-worker -f
```

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
