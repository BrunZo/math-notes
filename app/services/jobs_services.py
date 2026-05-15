from pathlib import Path

from fastapi import UploadFile

from app.helpers.fs_helpers import relative_paths_with_suffix
from app.helpers.jobs_helpers import save_uploaded_files, write_job_descriptor
from config.paths import INBOX_DIR, PENDING_DIR, TEX_DIR

_DASHBOARD_HTML = (
    Path(__file__).parent.parent.parent / "templates" / "jobs_dashboard.html"
)


def serve_dashboard() -> str:
    return _DASHBOARD_HTML.read_text()


def list_jobs() -> list[dict]:
    jobs: dict[str, str] = {}
    for p in relative_paths_with_suffix(TEX_DIR, ".tex"):
        jobs[p] = "done"
    for p in relative_paths_with_suffix(PENDING_DIR, ".tex"):
        jobs.setdefault(p, "compiling")
    for p in relative_paths_with_suffix(PENDING_DIR, ".error"):
        jobs.setdefault(p, "error")
    for p in relative_paths_with_suffix(INBOX_DIR, ".job"):
        jobs.setdefault(p, "pending")
    return [{"id": k, "status": v} for k, v in sorted(jobs.items())]


async def create_job(
    path: str, model: str, fidelity: str, files: list[UploadFile]
) -> dict:
    inbox_dir = INBOX_DIR / Path(path).parent
    stem = Path(path).name
    inbox_dir.mkdir(parents=True, exist_ok=True)
    saved = await save_uploaded_files(files, inbox_dir, stem)
    write_job_descriptor(inbox_dir, stem, model, fidelity, saved)
    return {"id": path, "status": "pending", "files": saved}
