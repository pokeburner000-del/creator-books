"""Creator Books local web app.

Run:  uvicorn app.main:app --reload     then open http://127.0.0.1:8000

Data stays on this machine: uploads are held in memory for the session only.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from creator_books.engine import Options, analyze
from creator_books.importers import Dataset, load_dir
from creator_books.models import Profile
from creator_books.packet import ledger_csv, to_markdown

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "sample_data"
STATIC = Path(__file__).with_name("static")

app = FastAPI(title="Creator Books")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SESSIONS: dict[str, dict] = {}  # sid -> {"ds": Dataset, "opts": Options, "last": dict}


class AnalyzeRequest(BaseModel):
    overrides: dict[str, dict] = {}
    rest_of_year_multiplier: float = 1.0
    extra_income: float = 0.0
    extra_expenses: float = 0.0
    salary_pct: float = 0.40
    admin_cost: float = 2_500.0
    profile: dict = {}  # edits to the client profile


def _run(sid: str, req: AnalyzeRequest | None = None) -> dict:
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "Session not found. Load data again.")
    if req is not None:
        if req.profile:
            merged = {**s["ds"].profile.__dict__, **req.profile}
            s["ds"].profile = Profile.from_dict(merged)
        s["opts"] = Options(overrides=req.overrides, rest_of_year_multiplier=req.rest_of_year_multiplier,
                            extra_income=req.extra_income, extra_expenses=req.extra_expenses,
                            salary_pct=req.salary_pct, admin_cost=req.admin_cost)
    try:
        result = analyze(s["ds"], s["opts"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    s["last"] = result
    return {"session": sid, **result}


def _new_session(ds: Dataset) -> str:
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"ds": ds, "opts": Options(), "last": None}
    return sid


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/samples")
def samples() -> list[dict]:
    out = []
    for d in sorted(SAMPLES.iterdir()):
        if d.is_dir():
            planted = d / "_PLANTED_ISSUES.md"
            title = planted.read_text(encoding="utf-8").splitlines()[0].lstrip("# ") if planted.exists() else d.name
            out.append({"name": d.name, "title": title})
    return out


@app.post("/api/sample/{name}")
def load_sample(name: str) -> dict:
    path = SAMPLES / name
    if not path.is_dir() or "/" in name or ".." in name:
        raise HTTPException(404, "No such sample")
    return _run(_new_session(load_dir(str(path))))


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)) -> dict:
    ds = Dataset()
    for f in files:
        raw = await f.read()
        try:
            ds.add_file(f.filename or "file.csv", raw.decode("utf-8-sig"))
        except Exception as e:  # keep going; report what failed
            ds.warnings.append(f"{f.filename}: {e}")
    if not ds.transactions:
        raise HTTPException(400, "No transactions found. " + " ".join(ds.warnings))
    if not any(x["kind"] == "profile" for x in ds.files):
        years = sorted({t.date.year for t in ds.transactions})
        ds.profile.tax_year = years[-1] if years[-1] in (2025, 2026) else date.today().year
        ds.warnings.append("No profile.json: assumed single filer, no prior-year tax. Edit the profile to refine.")
    return _run(_new_session(ds))


@app.post("/api/session/{sid}/analyze")
def reanalyze(sid: str, req: AnalyzeRequest) -> dict:
    return _run(sid, req)


def _last(sid: str) -> dict:
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    return s["last"] or _run(sid)


@app.get("/api/session/{sid}/packet.md")
def packet(sid: str) -> PlainTextResponse:
    a = _last(sid)
    name = (a["profile"].get("name") or "client").split(" (")[0].lower().replace(" ", "-")
    return PlainTextResponse(to_markdown(a), headers={
        "Content-Disposition": f'attachment; filename="creator-books-{name}-{a["tax_year"]}.md"'})


@app.get("/api/session/{sid}/packet-preview")
def packet_preview(sid: str) -> PlainTextResponse:
    return PlainTextResponse(to_markdown(_last(sid)))


@app.get("/api/session/{sid}/ledger.csv")
def ledger(sid: str) -> Response:
    a = _last(sid)
    return Response(ledger_csv(a), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="creator-books-ledger-{a["tax_year"]}.csv"'})
