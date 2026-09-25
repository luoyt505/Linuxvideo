"""静态页面：SPA 入口。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(tags=["pages"])

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@router.get("/", include_in_schema=False)
def index():
    """返回前端单页应用。"""
    html_file = STATIC_DIR / "index.html"
    if html_file.exists():
        return FileResponse(html_file, media_type="text/html")
    return HTMLResponse(
        "<h1>mediahub</h1><p>前端文件缺失，请确认 app/static/index.html 存在。</p>",
        status_code=200,
    )
