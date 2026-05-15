from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from app.helpers.jobs_helpers import ALLOWED_TYPES, FIDELITY_VALUES
from app.services import jobs_services
from config.paths import INBOX_DIR, TEX_DIR
from llm import list_models

jobs_router = APIRouter(prefix="/jobs")


@jobs_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(jobs_services.serve_dashboard())


@jobs_router.get("/")
async def list_jobs():
    return jobs_services.list_jobs()


@jobs_router.get("/models")
async def models():
    return list_models()


@jobs_router.post("/")
async def create_job(
    path: str = Form(...),
    model: str = Form(...),
    fidelity: str = Form("standard"),
    files: Annotated[list[UploadFile], File(...)] = ...,
):
    if ".." in Path(path).parts or Path(path).is_absolute():
        raise HTTPException(status_code=422, detail="Invalid path")
    if fidelity not in FIDELITY_VALUES:
        raise HTTPException(status_code=422, detail=f"Invalid fidelity: {fidelity}")
    if model not in list_models():
        raise HTTPException(status_code=422, detail=f"Unknown model: {model}")
    for f in files:
        if f.content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=415, detail=f"Unsupported type: {f.content_type}"
            )
    if (TEX_DIR / f"{path}.tex").exists():
        raise HTTPException(status_code=409, detail=f"Output already exists for {path}")
    if (INBOX_DIR / Path(path).parent / f"{Path(path).name}.job").exists():
        raise HTTPException(status_code=409, detail=f"Job already pending for {path}")
    return await jobs_services.create_job(path, model, fidelity, files)
