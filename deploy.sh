#!/usr/bin/env bash
set -euo pipefail

# ── config ────────────────────────────────────────────────────────────────────
REPO_DIR="${REPO_DIR:-$HOME/code/math-notes-viz}"
# ──────────────────────────────────────────────────────────────────────────────

cd "$REPO_DIR"
git pull origin main
docker compose build
docker compose up -d
