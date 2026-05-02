"""otakuracy MVP search API + UI."""
import math
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api import db

app = FastAPI(title="otakuracy API", version="0.1.0")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def _pagination(page: int, total: int, limit: int) -> dict:
    total_pages = max(1, math.ceil(total / limit))
    return {
        "page": page,
        "total": total,
        "limit": limit,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


def _format_date(val: str | None) -> str:
    if not val:
        return "日時未定"
    # YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
    if "T" in val:
        val = val.split("T")[0]
    parts = val.split("-")
    if len(parts) == 3:
        return f"{parts[0]}年{int(parts[1])}月{int(parts[2])}日"
    return val


def _format_price(price_min: Any, price_max: Any) -> str:
    if price_min is None and price_max is None:
        return "価格未定"
    if price_min == price_max or price_max is None:
        return f"¥{int(price_min):,}" if price_min else "無料"
    return f"¥{int(price_min):,} 〜 ¥{int(price_max):,}"


templates.env.filters["format_date"] = _format_date
templates.env.filters["format_price"] = _format_price


def _format_time(val) -> str:
    return val if val else "−"


templates.env.filters["format_time"] = _format_time


# ---------------------------------------------------------------------------
# REST API endpoints
# ---------------------------------------------------------------------------

@app.get("/api/events")
async def api_events(
    q: str = Query(""),
    tag: str = Query(""),
    tags: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
    sort: str = Query("near"),
):
    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    items, total = db.search_events(q=q, tag=tag, tags=tags_list, page=page, limit=limit, sort=sort)
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
    }


@app.get("/api/events/{event_id}")
async def api_event_detail(event_id: str):
    event = db.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.get("/api/tags")
async def api_tags(q: str = Query(""), limit: int = Query(50, ge=1, le=200)):
    tags = db.list_tags(q=q, limit=limit)
    return {"tags": tags}


# ---------------------------------------------------------------------------
# UI routes
# ---------------------------------------------------------------------------

@app.get("/sw.js")
async def service_worker():
    return FileResponse(str(STATIC_DIR / "sw.js"), media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/events", response_class=HTMLResponse)
async def events_list(
    request: Request,
    q: str = Query(""),
    tag: str = Query(""),
    tags: str = Query(""),
    page: int = Query(1, ge=1),
    sort: str = Query("near"),
):
    limit = 24
    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    items, total = db.search_events(q=q, tag=tag, tags=tags_list, page=page, limit=limit, sort=sort)
    pagination = _pagination(page, total, limit)
    return templates.TemplateResponse(
        request, "events.html",
        {
            "events": items,
            "q": q,
            "tag": tag,
            "tags": tags,
            "sort": sort,
            "pagination": pagination,
        },
    )


@app.get("/events/{event_id}", response_class=HTMLResponse)
async def event_detail(request: Request, event_id: str):
    event = db.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return templates.TemplateResponse(
        request, "event_detail.html",
        {"event": event},
    )




@app.get("/mylist", response_class=HTMLResponse)
async def mylist(request: Request):
    return templates.TemplateResponse(request, "mylist.html", {})

@app.get("/tags/{tag}", response_class=HTMLResponse)
async def tag_events(
    request: Request,
    tag: str,
    page: int = Query(1, ge=1),
):
    limit = 24
    items, total = db.get_events_for_tag(tag=tag, page=page, limit=limit)
    pagination = _pagination(page, total, limit)
    return templates.TemplateResponse(
        request, "tag_events.html",
        {
            "tag": tag,
            "events": items,
            "pagination": pagination,
        },
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=9000, reload=False)


if __name__ == "__main__":
    main()
