import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import fitz  # pymupdf
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from workflow.parsing import MODELS_BY_PROVIDER, MODEL_REGISTRY
from . import latex

_INBOX_DIR = Path(os.environ["INBOX_DIR"])
_OUTPUT_DIR = Path(os.environ["OUTPUT_DIR"])
_SECRET_TOKEN = os.environ["SECRET_TOKEN"]

_TEMPLATES = Path(__file__).parent.parent / "templates"
_INDEX_HTML = _TEMPLATES / "index.html"

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
_FIDELITY_VALUES = {"conservative", "standard"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    _INBOX_DIR.mkdir(parents=True, exist_ok=True)
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.method == "GET":
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[len("Bearer "):] != _SECRET_TOKEN:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/jobs")
async def list_jobs():
    jobs: dict[str, str] = {}

    if _OUTPUT_DIR.exists():
        for f in sorted(_OUTPUT_DIR.rglob("*.tex")):
            jobs[f.relative_to(_OUTPUT_DIR).with_suffix("").as_posix()] = "done"
        for f in sorted(_OUTPUT_DIR.rglob("*.error")):
            path = f.relative_to(_OUTPUT_DIR).with_suffix("").as_posix()
            jobs.setdefault(path, "error")

    if _INBOX_DIR.exists():
        for f in sorted(_INBOX_DIR.rglob("*.job")):
            path = f.relative_to(_INBOX_DIR).with_suffix("").as_posix()
            jobs.setdefault(path, "pending")

    return [{"id": k, "status": v} for k, v in sorted(jobs.items())]


@app.get("/models")
async def list_models():
    return MODELS_BY_PROVIDER


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(_INDEX_HTML.read_text())


@app.post("/job")
async def create_job(
    path: str = Form(...),
    model: str = Form(...),
    fidelity: str = Form("standard"),
    debug_model: str = Form(...),
    debug_iters: int = Form(3),
    files: Annotated[list[UploadFile], File(...)] = ...,
):
    if ".." in Path(path).parts or Path(path).is_absolute():
        raise HTTPException(status_code=422, detail="Invalid path")
    if fidelity not in _FIDELITY_VALUES:
        raise HTTPException(status_code=422, detail=f"Invalid fidelity: {fidelity}")
    if model not in MODEL_REGISTRY:
        raise HTTPException(status_code=422, detail=f"Unknown model: {model}")
    if debug_model not in MODEL_REGISTRY:
        raise HTTPException(status_code=422, detail=f"Unknown debug_model: {debug_model}")
    if debug_iters < 0:
        raise HTTPException(status_code=422, detail="debug_iters must be >= 0")
    for f in files:
        if f.content_type not in _ALLOWED_TYPES:
            raise HTTPException(status_code=415, detail=f"Unsupported type: {f.content_type}")

    job_path = Path(path)
    stem = job_path.name
    inbox_dir = _INBOX_DIR / job_path.parent

    if (_OUTPUT_DIR / f"{path}.tex").exists():
        raise HTTPException(status_code=409, detail=f"Output already exists for {path}")
    if (inbox_dir / f"{stem}.job").exists():
        raise HTTPException(status_code=409, detail=f"Job already pending for {path}")

    inbox_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    page = 1
    for f in files:
        raw = await f.read()
        if f.content_type == "application/pdf":
            pdf_doc = fitz.open(stream=raw, filetype="pdf")
            for pdf_page in pdf_doc:
                pix = pdf_page.get_pixmap(dpi=200)
                dest = inbox_dir / f"{stem}_{page:02d}.png"
                dest.write_bytes(pix.tobytes("png"))
                saved.append(dest.name)
                page += 1
        else:
            suffix = Path(f.filename).suffix.lower() if f.filename else ".jpg"
            dest = inbox_dir / f"{stem}_{page:02d}{suffix}"
            dest.write_bytes(raw)
            saved.append(dest.name)
            page += 1

    (inbox_dir / f"{stem}.job").write_text(
        json.dumps({
            "model": model, "fidelity": fidelity, "images": sorted(saved),
            "debug_model": debug_model, "debug_iters": debug_iters,
        }),
        encoding="utf-8",
    )

    return {"id": path, "status": "pending", "files": saved}


@app.get("/job/{path:path}")
async def get_job_output(path: str):
    p = Path(path)
    suffix = p.suffix.lower()
    stem = p.stem
    parent = p.parent

    if suffix not in {".tex", ".pdf"}:
        raise HTTPException(status_code=400, detail="Path must end in .tex or .pdf")

    tex_path = _OUTPUT_DIR / parent / f"{stem}.tex"

    if suffix == ".tex":
        if tex_path.exists():
            return Response(content=tex_path.read_text(encoding="utf-8"), media_type="text/plain")
    elif suffix == ".pdf":
        try:
            if stem == "master":
                pdf_bytes = latex.compile_master(_OUTPUT_DIR / parent)
            elif tex_path.exists():
                pdf_bytes = latex.compile_single(tex_path)
            else:
                pdf_bytes = None
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        if pdf_bytes is not None:
            return Response(content=pdf_bytes, media_type="application/pdf")

    error_path = _OUTPUT_DIR / parent / f"{stem}.error"
    if error_path.exists():
        raise HTTPException(status_code=500, detail=error_path.read_text(encoding="utf-8"))

    if (_INBOX_DIR / parent / f"{stem}.job").exists():
        raise HTTPException(status_code=202, detail="Job is pending")

    raise HTTPException(status_code=404, detail="Not found")
