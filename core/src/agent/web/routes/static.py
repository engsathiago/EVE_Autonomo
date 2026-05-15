"""Serve arquivos estáticos do frontend (public/) com Cache-Control adequado."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

from agent.observability.logger import get_logger

log = get_logger(__name__)

_PUBLIC_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "webui" / "public"

_CACHE_IMMUTABLE_EXTS = {".js", ".css", ".woff2", ".woff", ".ttf", ".svg", ".ico", ".png"}
_NO_CACHE = "no-cache, no-store, must-revalidate"
_LONG_CACHE = "public, max-age=86400, immutable"


def make_static_router() -> APIRouter:
    router = APIRouter()

    @router.get("/", include_in_schema=False)
    async def index(request: Request) -> Response:
        return _serve_file(Path("index.html"))

    @router.get("/{path:path}", include_in_schema=False)
    async def static_file(path: str) -> Response:
        # Proíbe path traversal
        safe = (Path("/") / path).resolve().relative_to(Path("/"))
        return _serve_file(safe)

    return router


def _serve_file(rel_path: Path) -> Response:
    full = (_PUBLIC_DIR / rel_path).resolve()
    # Garante que está dentro de public/
    try:
        full.relative_to(_PUBLIC_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso negado")

    if not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail="Não encontrado")

    content = full.read_bytes()
    mime = mimetypes.guess_type(str(full))[0] or "application/octet-stream"
    cache = _LONG_CACHE if full.suffix in _CACHE_IMMUTABLE_EXTS else _NO_CACHE
    return Response(content=content, media_type=mime, headers={"Cache-Control": cache})
