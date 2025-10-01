from __future__ import annotations as _annotations
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, HTMLResponse
from fastui import prebuilt_html

router = APIRouter(
    prefix="/default-page",
)


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt() -> str:
    return "User-agent: *\nAllow: /"


@router.get("/favicon.ico", status_code=404, response_class=PlainTextResponse)
async def favicon_ico() -> str:
    return "page not found"


@router.get("/{path:path}")
async def html_landing() -> HTMLResponse:
    return HTMLResponse(prebuilt_html(title="FastUI Demo"))
