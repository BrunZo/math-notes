from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from typing import Annotated

from .config import settings
from . import latex


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(lifespan=lifespan)

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_TEMPLATES = Path(__file__).parent.parent / "templates"
_INDEX_HTML = _TEMPLATES / "index.html"
_COURSE_FULL_HTML = _TEMPLATES / "course_full.html"
_COURSES_CSV = Path(__file__).parent.parent / "courses.csv"


def _load_course_names() -> dict[str, str]:
    if not _COURSES_CSV.exists():
        return {}
    names: dict[str, str] = {}
    for line in _COURSES_CSV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and "," in line:
            cid, name = line.split(",", 1)
            names[cid.strip()] = name.strip()
    return names


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.method == "GET":
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[len("Bearer "):] != settings.SECRET_TOKEN:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(_INDEX_HTML.read_text())


_FIDELITY_VALUES = {"conservative", "standard", "liberal"}


@app.post("/jobs")
async def create_job(
    course_id: str = Form(...),
    lecture_num: int = Form(...),
    fidelity: str = Form("standard"),
    files: Annotated[list[UploadFile], File(...)] = ...,
):
    if fidelity not in _FIDELITY_VALUES:
        raise HTTPException(status_code=422, detail=f"Invalid fidelity: {fidelity}")
    for f in files:
        if f.content_type not in _ALLOWED_TYPES:
            raise HTTPException(status_code=415, detail=f"Unsupported media type: {f.content_type}")

    lecture_stem = f"{lecture_num:02d}"
    tex_path = settings.OUTPUT_DIR / course_id / f"{lecture_stem}.tex"
    if tex_path.exists():
        raise HTTPException(status_code=409, detail=f"Lecture {lecture_stem} already has a .tex file for course '{course_id}'")
    batch_path = settings.INBOX_DIR / course_id / f"{lecture_stem}.batch"
    if batch_path.exists():
        raise HTTPException(status_code=409, detail=f"Lecture {lecture_stem} is already pending for course '{course_id}'")

    inbox_dir = settings.INBOX_DIR / course_id
    inbox_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for page, f in enumerate(files, start=1):
        suffix = Path(f.filename).suffix.lower() if f.filename else ".jpg"
        dest = inbox_dir / f"{lecture_num:02d}_{page:02d}{suffix}"
        dest.write_bytes(await f.read())
        saved.append(dest.name)

    (inbox_dir / f"{lecture_stem}.batch").write_text("\n".join(sorted(saved)))
    (inbox_dir / f"{lecture_stem}.fidelity").write_text(fidelity)

    return {"status": "pending", "files": saved}


@app.get("/courses")
async def list_courses():
    ids: set[str] = set()
    for base in (settings.INBOX_DIR, settings.OUTPUT_DIR):
        if base.exists():
            ids.update(p.name for p in base.iterdir() if p.is_dir())
    names = _load_course_names()
    return [{"id": cid, "name": names.get(cid, cid)} for cid in sorted(ids)]


@app.get("/courses/{course_id}/status")
async def course_status(course_id: str):
    lectures: dict[str, dict] = {}

    out_dir = settings.OUTPUT_DIR / course_id
    if out_dir.exists():
        for f in out_dir.iterdir():
            if f.name == "master.tex":
                continue
            if f.suffix == ".tex":
                lectures[f.stem] = {"lecture_num": f.stem, "status": "done"}
            elif f.suffix == ".error" and f.stem not in lectures:
                lectures[f.stem] = {"lecture_num": f.stem, "status": "error",
                                     "error_msg": f.read_text()}

    inbox_dir = settings.INBOX_DIR / course_id
    if inbox_dir.exists():
        for f in inbox_dir.iterdir():
            if f.suffix == ".batch" and f.stem not in lectures:
                lectures[f.stem] = {"lecture_num": f.stem, "status": "pending"}

    return {
        "course_id": course_id,
        "lectures": sorted(lectures.values(), key=lambda j: j["lecture_num"]),
    }


@app.get("/courses/{course_id}/full", response_class=HTMLResponse)
async def course_full_page(course_id: str):
    return HTMLResponse(_COURSE_FULL_HTML.read_text())


@app.get("/courses/{course_id}/pdf")
async def course_pdf(course_id: str):
    master_path = settings.OUTPUT_DIR / course_id / "master.tex"
    if not master_path.exists():
        raise HTTPException(status_code=404, detail="No master.tex for this course yet")

    try:
        pdf_bytes = latex.compile(master_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{course_id}.pdf"'},
    )


@app.get("/courses/{course_id}/lectures")
async def course_lectures(course_id: str):
    out_dir = settings.OUTPUT_DIR / course_id
    if not out_dir.exists():
        raise HTTPException(status_code=404, detail="Course not found")
    files = sorted(
        (f for f in out_dir.glob("*.tex") if f.name != "master.tex"),
        key=lambda f: f.stem,
    )
    return [{"lecture_num": f.stem, "content": f.read_text(encoding="utf-8")} for f in files]
