"""FastAPI backend pro TreeLabeler."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import load_categories
from .db import Database
from .loader import load_points

STATIC_DIR = Path(__file__).resolve().parent / "static"
POINT_EXTS = (".las", ".laz")


class LabelIn(BaseModel):
    file_id: int
    tree_type: str | None = None
    quality: str | None = None
    note: str | None = None


class DataDirIn(BaseModel):
    data_dir: str


def _find_external_sqlite(data_dir: Path) -> Path | None:
    """Raycloudtools sqlite s tabulkou trees (muze se jmenovat <laz>.db nebo
    <laz>.laz.sqlite apod.). Soubor cloud_segmented_-1 nikdy nevraci."""
    import sqlite3 as _sq
    for f in sorted(data_dir.iterdir()):
        if f.suffix.lower() not in (".db", ".sqlite"):
            continue
        if ".labels.sqlite" in f.name.lower():     # tohle je nas zapisnik, ne trees
            continue
        if Database.parse_section_id(f.name) == -1:
            continue
        try:
            con = _sq.connect(f"file:{f}?mode=ro", uri=True)
            has = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trees'"
            ).fetchone()
            con.close()
            if has:
                return f
        except _sq.Error:
            pass
    return None


def _is_readonly_source_dir(data_dir: Path) -> bool:
    """Slozka v source_data/ je immutable po AGENTS (§4.2) — parser nesmi zapisovat
    do zadneho .db/.sqlite uvnitr ni. Labels pro takova data jdou do pracovni kopie v
    working/."""
    try:
        resolved = data_dir.resolve()
    except OSError:
        return False
    parts = {p.lower() for p in resolved.parts}
    return "source_data" in parts


def _can_write(path: Path) -> bool:
    """Overi, ze do souboru lze realne zapisovat (sqlite UNLOCK test)."""
    import sqlite3 as _sq
    try:
        con = _sq.connect(str(path))
        con.execute("PRAGMA journal_mode=WAL")
        con.close()
        return True
    except (_sq.Error, OSError):
        return False


def _open_db(data_dir: Path) -> tuple[Path, Database]:
    """Vrati (labels_db_path, Database). Pravidla:

    1. source_data/ je IMMUTABLE po AGENTS (§4.2). Pokud je data_dir pod
       source_data/, vzdycky zkopirujeme sqlite do working/<dir>_labels/ a
       otevreme KOPENI — zadny zapis se nedostane do source_data.
    2. Pokud data mimo source_data a raycloudtools sqlite existuje a lze do ni
       zapisovat → otevreme primo ji (single-file mode, labely u dat).
    3. Pokud sqlite neni writable, vytvorime vedle `<name>.labels.sqlite` a
       trees pripojime read-only ATTACHem.
    4. Pokud trees neni → `<slozka>.db` jako driv.
    """
    trees_path = _find_external_sqlite(data_dir)
    if _is_readonly_source_dir(data_dir):
        # 1) vzdy pracovat v working/ kopii — nedotknout se source_data
        out_dir = Path.cwd() / "working" / (data_dir.name + "_labels")
        out_dir.mkdir(parents=True, exist_ok=True)
        if trees_path is not None:
            work_copy = out_dir / trees_path.name
            if not work_copy.exists() or work_copy.stat().st_size != trees_path.stat().st_size:
                work_copy.write_bytes(trees_path.read_bytes())
            # single-file mode proti working kopii — zapisujeme do ni
            return work_copy, Database(work_copy, data_dir=data_dir, trees_db_path=None)
        labels_path = out_dir / f"{data_dir.name}.db"
        return labels_path, Database(labels_path, data_dir=data_dir, trees_db_path=None)

    if trees_path is not None and _can_write(trees_path):
        return trees_path, Database(trees_path, data_dir=data_dir, trees_db_path=None)

    if trees_path is not None:
        name = trees_path.name.replace(".laz.sqlite", ".labels.sqlite")
    else:
        name = f"{data_dir.name}.db"
    labels_path = data_dir / name
    return labels_path, Database(labels_path, data_dir=data_dir, trees_db_path=trees_path)


def _scan_dir(db: Database, data_dir: Path, count_points: bool = True) -> int:
    added = 0
    laz_names = []
    for p in sorted(data_dir.iterdir()):
        if p.suffix.lower() in POINT_EXTS:
            sid = db.parse_section_id(p.name)
            if sid == -1:
                # cloud_segmented_-1.laz je VYHRADNE zdrojem okolnich bodu.
                # Nikdy nevstupuje do naseho analyzy ani do treelabeler files.
                continue
            laz_names.append(p.name)
            npts = None
            if count_points:
                try:
                    npts = len(load_points(p)["positions"])
                except Exception:
                    npts = None
            db.upsert_file(p, npts)
            added += 1
    # overeni parovani (krok 1) — reportuje se v bootstrap endpointu
    if db.external:
        db.pairing_report = db.verify_pairing(laz_names)
    from .loader import load_bbox_index
    load_bbox_index(data_dir, db)  # preserve bboxes in DB for context overlay
    return added


def create_app(data_dir: Path | None, config_path: Path | None = None) -> FastAPI:
    cfg_data = load_categories()
    db: Database | None = None
    db_path = None
    if data_dir is not None:
        data_dir = data_dir.resolve()
        db_path, db = _open_db(data_dir)
        if cfg_data["categories"]:
            db.sync_categories(cfg_data["categories"])

    app = FastAPI(title="TreeLabeler")
    app.state.db = db
    app.state.data_dir = data_dir
    app.state.db_path = db_path

    cfg = cfg_data
    app.state.config = cfg

    # zabránit cache statických souborů — jinak browser po reloadu drží staré app.js
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    class NoCacheMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            resp = await call_next(request)
            if request.url.path.startswith("/static/") or request.url.path in ("/", "/index.html"):
                resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
                resp.headers["Pragma"] = "no-cache"
                resp.headers["Expires"] = "0"
            return resp

    app.add_middleware(NoCacheMiddleware)

    @app.get("/api/bootstrap")
    def bootstrap() -> dict:
        cfg = app.state.config
        db = app.state.db
        data = {
            "data_dir": str(app.state.data_dir) if app.state.data_dir else None,
            "db": app.state.db_path.name if app.state.db_path else None,
            "groups": cfg.get("groups", []),
            "files": [],
            "progress": {"total": 0, "labeled": 0},
        }
        if db is not None:
            data["files"] = db.list_files()
            data["progress"] = db.progress()
            data["categories"] = db.list_categories()
            data["external_db"] = db.external
            data["pairing"] = getattr(db, "pairing_report", None)
        else:
            data["categories"] = cfg.get("categories", [])
        return data

    @app.post("/api/set-datadir")
    def set_datadir(payload: DataDirIn) -> dict:
        new_dir = Path(payload.data_dir).expanduser().resolve()
        if not new_dir.is_dir():
            raise HTTPException(400, f"slozka neexistuje: {new_dir}")
        if app.state.db is not None:
            app.state.db.close()
        new_db_path, new_db = _open_db(new_dir)
        new_db.sync_categories(app.state.config.get("categories", []))
        count = _scan_dir(new_db, new_dir, count_points=False)
        app.state.db = new_db
        app.state.data_dir = new_dir
        app.state.db_path = new_db_path
        return {
            "ok": True,
            "data_dir": str(new_dir),
            "db": new_db_path.name,
            "scanned": count,
            "progress": new_db.progress(),
        }


    @app.get("/api/files")
    def files() -> dict:
        db = app.state.db
        if db is None:
            return {"files": [], "progress": {"total": 0, "labeled": 0}}
        return {"files": db.list_files(), "progress": db.progress()}

    @app.get("/api/next-unlabeled")
    def next_unlabeled() -> dict:
        if app.state.db is None:
            raise HTTPException(400, "no data folder loaded")
        nid = app.state.db.next_unlabeled_id()
        return {"file_id": nid}

    @app.get("/api/file/{file_id}")
    def file_info(file_id: int) -> dict:
        if app.state.db is None:
            raise HTTPException(400, "no data folder loaded")
        rec = app.state.db.get_file(file_id)
        if not rec:
            raise HTTPException(404, "file not found")
        return rec

    @app.get("/api/file/{file_id}/points")
    def file_points(file_id: int) -> dict:
        if app.state.db is None:
            raise HTTPException(400, "no data folder loaded")
        db = app.state.db
        rec = db.get_file(file_id)
        if not rec:
            raise HTTPException(404, "file not found")
        # -1 soubor nesmi nikdy slouzit jako analyzovany strom
        if Database.parse_section_id(rec["filename"]) == -1:
            raise HTTPException(410, "excluded: special background file")
        path = Path(rec["abs_path"])
        if not path.exists():
            raise HTTPException(404, f"missing file: {path}")
        cloud = load_points(path)
        pos_b64 = base64.b64encode(cloud["positions"].tobytes()).decode("ascii")
        col_b64 = base64.b64encode(cloud["colors"].tobytes()).decode("ascii")
        out = {
            "file_id": file_id,
            "n_points": cloud["n_points"],
            "origin": cloud["origin"],
            "positions_b64": pos_b64,
            "colors_b64": col_b64,
        }
        # dist2dmt (vyskova korekce meritkove mrizky) + section_id z externi DB
        sid = rec.get("section_id")
        out["section_id"] = sid
        meta = db.get_tree_meta(sid) if (db.external and sid is not None) else None
        out["dist2dmt"] = (meta or {}).get("dist2dmt")
        return out

    @app.post("/api/label")
    def set_label(payload: LabelIn) -> dict:
        if app.state.db is None:
            raise HTTPException(400, "no data folder loaded")
        db = app.state.db
        rec = db.get_file(payload.file_id)
        if not rec:
            raise HTTPException(404, "file not found")
        if payload.tree_type and db.get_category_id(payload.tree_type) is None:
            raise HTTPException(400, f"unknown tree_type: {payload.tree_type}")
        if payload.quality and db.get_category_id(payload.quality) is None:
            raise HTTPException(400, f"unknown quality: {payload.quality}")
        if not payload.tree_type and not payload.quality:
            raise HTTPException(400, "nic k ulozeni")
        db.set_label(payload.file_id, tree_type=payload.tree_type, quality=payload.quality, note=payload.note)
        return {
            "ok": True,
            "file_id": payload.file_id,
            "tree_type": payload.tree_type,
            "quality": payload.quality,
            "progress": db.progress(),
            "next_file_id": db.next_unlabeled_id(),
        }

    @app.post("/api/scan")
    def scan() -> dict:
        if app.state.db is None:
            raise HTTPException(400, "no data folder loaded")
        added = _scan_dir(app.state.db, app.state.data_dir, count_points=False)
        return {"added_or_updated": added, "progress": app.state.db.progress()}

    @app.get("/api/file/{file_id}/context")
    def file_context(file_id: int, max_points: int = 800_000) -> dict:
        """Body okoli stromu.

        Volby:
          - bboxes vsech mračen se naplni behem scanu (hlavicky LAZ).
          - target = bbox stromu (+1m buffer), sousedi = primese stromy
            (jejich puvodni bbox, zadny buffer).
          - -1 mracno ohnictvene na target + buffer (jen okoli targetu,
            ne celej scene).
          - Barva: target strom → colored levj steerom / neighbor stromy →
            tlumena zelena / -1 → seda.
        """
        from .loader import load_context_for_tree
        if app.state.db is None:
            raise HTTPException(400, "no data folder loaded")
        db = app.state.db
        rec = db.get_file(file_id)
        if not rec:
            raise HTTPException(404, "file not found")
        if Database.parse_section_id(rec["filename"]) == -1:
            raise HTTPException(410, "excluded: special background file")

        ctx = load_context_for_tree(
            db=db,
            data_dir=app.state.data_dir,
            tree_id=file_id,
            buffer=1.0,
            max_points=max_points,
        )
        if ctx is None:
            return {"file_id": file_id, "n_points": 0,
                    "segments_b64": None, "reason": "empty window"}

        # base64-encode each part separately (positions are float64)
        out = {
            "file_id": file_id,
            "target_bbox": ctx["target_bbox"],
            "buffer": ctx["buffer"],
            "neighbors": ctx["neighbors"],
            "segments": [],
            "background": None,
        }
        for seg in ctx["segments"]:
            out["segments"].append({
                "tree_id": seg["tree_id"],
                "n": seg["n"],
                "positions_b64": base64.b64encode(
                    seg["positions"].tobytes()
                ).decode("ascii"),
            })
        if ctx["background"]:
            out["background"] = {
                "n": ctx["background"]["n"],
                "positions_b64": base64.b64encode(
                    ctx["background"]["positions"].tobytes()
                ).decode("ascii"),
            }
        return out

    @app.get("/api/export.csv")
    def export_csv() -> FileResponse:
        if app.state.db is None:
            raise HTTPException(400, "no data folder loaded")
        db = app.state.db
        ddir = app.state.data_dir
        rows = db.list_files()
        if _is_readonly_source_dir(ddir):
            out_dir = Path.cwd() / "working" / (ddir.name + "_labels")
            out_dir.mkdir(parents=True, exist_ok=True)
        else:
            out_dir = ddir
        csv_path = out_dir / f"{ddir.name}_labels.csv"
        lines = ["tree_id,filename,abs_path,tree_type,quality"]
        for r in rows:
            tt = r.get("tree_type") or ""
            ql = r.get("quality") or ""
            lines.append(f'{r.get("tree_id","")},{r["filename"]},{r["abs_path"]},{tt},{ql}')
        csv_path.write_text("\n".join(lines), encoding="utf-8")
        return FileResponse(csv_path, filename=csv_path.name, media_type="text/csv")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico")
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.ico")

    # pocatecni scan slozky (only if data folder was given)
    if app.state.db is not None and app.state.data_dir is not None:
        _scan_dir(app.state.db, app.state.data_dir, count_points=False)
    return app
