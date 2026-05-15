import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.routes.jobs_routes import jobs_router
from app.routes.notes_routes import notes_router
from config.paths import INBOX_DIR as _INBOX_DIR
from config.paths import PENDING_DIR as _PENDING_DIR
from config.paths import TEX_DIR as _TEX_DIR

_SECRET_TOKEN = os.environ["SECRET_TOKEN"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    _INBOX_DIR.mkdir(parents=True, exist_ok=True)
    _PENDING_DIR.mkdir(parents=True, exist_ok=True)
    _TEX_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(jobs_router)
app.include_router(notes_router)


_AUTH_EXEMPT = {"/health", "/jobs/dashboard"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in _AUTH_EXEMPT or path.startswith("/notes"):
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[len("Bearer ") :] != _SECRET_TOKEN:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "ok"}
