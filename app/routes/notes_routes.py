from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from app.services import notes_services

notes_router = APIRouter(prefix="/notes")


@notes_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(notes_services.serve_dashboard())


@notes_router.get("/")
async def list_notes():
    return notes_services.list_notes()


@notes_router.get("/{path:path}")
async def get_note(path: str):
    if Path(path).suffix.lower() not in {".tex", ".pdf"}:
        raise HTTPException(status_code=400, detail="Path must end in .tex or .pdf")
    content, media_type = notes_services.get_note(path)
    return Response(content=content, media_type=media_type)
