"""Redpen web app: FastAPI backend + static frontend.

Run locally:  uvicorn app:app --reload
"""

import json
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from redpen import config, pipeline
from redpen.images import ImageError, to_data_url
from redpen.llm import Ledger, ModelError

ROOT = Path(__file__).parent
SAMPLES = ROOT / "samples"

app = FastAPI(title="Redpen", version="1.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/samples", StaticFiles(directory=SAMPLES), name="samples")

# ---------------------------------------------------------------- rate limiting (public demo)

_hits: dict[str, deque] = defaultdict(deque)


def check_rate(request: Request) -> None:
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    now = time.time()
    hits = _hits[ip]
    while hits and now - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= config.MAX_REQUESTS_PER_HOUR:
        raise HTTPException(429, "Demo limit reached for this hour. Please try again later.")
    hits.append(now)


@app.exception_handler(ModelError)
def model_error(_: Request, e: ModelError):
    """Model failures become readable 502s instead of stack traces."""
    return JSONResponse(status_code=502, content={"detail": str(e)})


# ---------------------------------------------------------------- routes


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "models": {"vision": config.MODEL_VISION, "fast": config.MODEL_FAST, "reasoning": config.MODEL_REASONING}}


@app.get("/api/sample")
def sample(set: str = "neat"):
    """Sample class so anyone (including judges) can try Redpen without their own sheets.

    set=neat: tidy handwriting. set=messy: sloppy handwriting photographed badly.
    """
    folder = "sheets_messy" if set == "messy" else "sheets"
    data = json.loads((SAMPLES / "class.json").read_text())
    students = [
        {"name": s["name"], "pages": [f"/samples/{folder}/{s['name'].lower().replace(' ', '_')}.jpg"]}
        for s in data["students"]
    ]
    return {"answer_key": (SAMPLES / "answer_key.txt").read_text(), "students": students}


class RubricIn(BaseModel):
    answer_key: str


@app.post("/api/rubric")
def rubric(body: RubricIn, request: Request):
    if not body.answer_key.strip():
        raise HTTPException(400, "Paste your answer key first.")
    if len(body.answer_key) > 20_000:
        raise HTTPException(400, "Answer key is too long (max 20,000 characters).")
    check_rate(request)
    ledger = Ledger()
    return {"rubric": pipeline.structure_rubric(body.answer_key, ledger), "usage": ledger.to_list()}


@app.post("/api/read")
def read(request: Request, rubric: str = Form(...), pages: list[UploadFile] = File(...)):
    if not pages:
        raise HTTPException(400, "Upload at least one page.")
    if len(pages) > config.MAX_PAGES_PER_SHEET:
        raise HTTPException(400, f"At most {config.MAX_PAGES_PER_SHEET} pages per student.")
    rub = json.loads(rubric)
    urls = []
    for page in pages:
        raw = page.file.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
        if len(raw) > config.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(400, f"{page.filename} is larger than {config.MAX_UPLOAD_MB} MB.")
        try:
            urls.append(to_data_url(raw))
        except ImageError as e:
            raise HTTPException(400, f"{page.filename}: {e}") from e
    check_rate(request)
    ledger = Ledger()
    return {"reading": pipeline.read_sheet(urls, rub, ledger), "usage": ledger.to_list()}


class GradeIn(BaseModel):
    rubric: dict
    reading: dict


@app.post("/api/grade")
def grade(body: GradeIn, request: Request):
    check_rate(request)
    ledger = Ledger()
    return {"grading": pipeline.grade_sheet(body.rubric, body.reading, ledger), "usage": ledger.to_list()}


class ReportIn(BaseModel):
    rubric: dict
    students: list[dict]


@app.post("/api/report")
def report(body: ReportIn, request: Request):
    if not body.students:
        raise HTTPException(400, "Grade at least one student first.")
    check_rate(request)
    ledger = Ledger()
    return {"report": pipeline.class_report(body.rubric, body.students, ledger), "usage": ledger.to_list()}


class TranslateIn(BaseModel):
    text: str
    language: str


@app.post("/api/translate")
def translate(body: TranslateIn, request: Request):
    if len(body.text) > 5000:
        raise HTTPException(400, "Text too long.")
    check_rate(request)
    ledger = Ledger()
    return {"text": pipeline.translate(body.text, body.language, ledger), "usage": ledger.to_list()}
