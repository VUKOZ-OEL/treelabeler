"""SQLite databaze pro TreeLabeler (vytvari se v datove slozce).

Schema v2 (2026-09): tree_id je primarni klic temer vsude a sedi presne na
cislo v nazvu souboru (cloud_segmented_<tree_id>.laz) a na section_id z
raycloudtools tabulkou trees. Tabulky labels/files odkazuji na tree_id.
Legacy tabulky (s file_id) se pri otevreni automaticky zmigruji.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  tree_id INTEGER PRIMARY KEY NOT NULL,
  filename TEXT NOT NULL,
  abs_path TEXT NOT NULL UNIQUE,
  n_points INTEGER,
  imported_at TEXT NOT NULL,
  x_min REAL, x_max REAL,
  y_min REAL, y_max REAL,
  z_min REAL, z_max REAL
);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  grp TEXT,
  shortcut TEXT,
  description TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS labels (
  tree_id INTEGER NOT NULL UNIQUE,
  category_id INTEGER,
  quality_category_id INTEGER,
  labeled_at TEXT NOT NULL,
  note TEXT,
  FOREIGN KEY (tree_id) REFERENCES files(tree_id),
  FOREIGN KEY (category_id) REFERENCES categories(id),
  FOREIGN KEY (quality_category_id) REFERENCES categories(id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Ucel databaze: treelabeler labeluje. Pokud trees_db_path je None, db_path
    JE samo raycloudtools sqlite (tabulka trees uz v nem existuje) a treelabeler
    si do nej doplni vlastni tabulky vedle — zapisujeme primo do it. Pokud
    trees_db_path je zadano, db_path je NASE .labels.sqlite (tam zapisujeme)
    a raycloudtools sqlite je ATTACHovana read-only jako trees_db (pouze cteni)."""

    def __init__(self, db_path: Path, data_dir: Path | None = None,
                 trees_db_path: Path | None = None):
        self.db_path = db_path                 # kam se zapisuje (labels/files/categories)
        self.data_dir = data_dir
        self.trees_db_path = trees_db_path     # odkud se pouze cte trees (None = primo v db_path)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # detekce: ma main schema tabulku trees? pak je to samotny raycloudtools DB.
        has_trees = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trees'"
        ).fetchone() is not None
        # doplneni nasho schema (files/categories/labels) vedle pripadnych trees
        self.conn.executescript(SCHEMA)
        self._migrate()

        if trees_db_path is not None and trees_db_path.exists():
            # read-only attach: zajistime ochranu zapisu pres URI
            # ATTACH neumi mode=ro — provozni garance:  nikdy nezapisujeme do trees_db.*
            self.conn.execute(f"ATTACH DATABASE '{trees_db_path.as_posix()}' AS trees_db")
            self.external = True
            self._trees = self._load_trees()
        elif has_trees:
            # main schema obsahuje trees → jediny soubor, oboji v nem.
            # Doplni tree_id alias vedle section_id pro ciste refence (srovne
            # vyzadavek uzivatele: v tabulce trees = column tree_id).
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(trees)")}
            if "section_id" in cols and "tree_id" not in cols:
                self.conn.execute("ALTER TABLE trees ADD COLUMN tree_id INTEGER")
                self.conn.execute("UPDATE trees SET tree_id = CAST(section_id AS INTEGER)")
            self.external = True
            self._trees = self._load_trees_main()
        else:
            self.external = False
            self._trees = None
        self.conn.commit()

    # --- externi trees DB (attach/inline, pouze cteni do pameti) -----------
    def _load_trees(self) -> dict:
        """Z attachovane trees_db.trees (fallback rezim)."""
        return self._load_trees_from("trees_db.trees")

    def _load_trees_main(self) -> dict:
        """Z main.trees (jednosouborovy rezim — treelabeler zapisuje do stejneho souboru)."""
        return self._load_trees_from("main.trees")

    def _load_trees_from(self, qual: str) -> dict:
        trees = {}
        cur = self.conn.execute(f"SELECT * FROM {qual}")
        for r in cur.fetchall():
            keys = set(r.keys())
            tid = r["tree_id"] if "tree_id" in keys else r["section_id"] if "section_id" in keys else None
            if tid is None:
                continue
            trees[int(tid)] = dict(r)
        return trees

    def _migrate(self):
        """Migrace pro starsi databaze. db.py schema v1 (2025-09) -> v2 (2025-12).
        files: id -> tree_id (s nacitanim cisla z filename, kdyz lze).
        labels: file_id -> tree_id.  Tabulky labels presunou 1:1.
        """
        # categories: doplneni grp sloupce z legacy
        cur = self.conn.execute("PRAGMA table_info(categories)")
        cols = {r["name"] for r in cur.fetchall()}
        if "grp" not in cols:
            self.conn.execute("ALTER TABLE categories ADD COLUMN grp TEXT")

        # labels: prejmenovani file_id -> tree_id (sqlite >= 3.25)
        lcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(labels)")}
        if lcols and "tree_id" not in lcols and "file_id" in lcols:
            self.conn.execute("ALTER TABLE labels RENAME COLUMN file_id TO tree_id")

        # bbox columns (schema v2.1) — doplni do existujicich DB
        fcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(files)")}
        if "x_min" not in fcols:
            for col in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max"):
                self.conn.execute(f"ALTER TABLE files ADD COLUMN {col} REAL")
                fcols.add(col)

        # files: pokud je stary schema (ma 'id' a nema 'tree_id'), prekopirujeme
        if "tree_id" not in fcols and "id" in fcols:
            # stara primarni colum id je INTEGER — nepreme si ji za tree_id, protoze
            # lazi se naplni znovu z disku; pro jednoduchost drop + recreate + naplnime
            # z rows (pokud je tabulka prazdna, jen recreate)
            rows = self.conn.execute(
                'SELECT id, filename, abs_path, n_points, imported_at FROM files'
            ).fetchall()
            self.conn.execute("DROP TABLE files")
            self.conn.execute("""CREATE TABLE files (
              tree_id INTEGER PRIMARY KEY NOT NULL,
              filename TEXT NOT NULL,
              abs_path TEXT NOT NULL UNIQUE,
              n_points INTEGER,
              imported_at TEXT NOT NULL
            )""")
            for r in rows:
                tid = self.parse_section_id(r["filename"])
                if tid is None or tid == -1:
                    continue  # legacy rows bez cisla — nelze zachovat, dropujeme
                self.conn.execute(
                    "INSERT OR REPLACE INTO files (tree_id, filename, abs_path, n_points, imported_at) VALUES (?,?,?,?,?)",
                    (tid, r["filename"], r["abs_path"], r["n_points"], r["imported_at"]),
                )
            # take migrujeme zpuvodnich labels: jejich file_id bylo stare f.id;
            # po prepaleni nemame mapping — pravdepodobne je ok tabulku vymazat.
            # (Presto zkontrolujeme, zda legacy 'file_id' neexistuje; po nasem
            # ALTER RENAME uz by mel byt obsazen 'tree_id' sloupec s pridelenym
            # klicem z minule session — ten ale nema smysl, protoze tree_id
            # je nyni semanticke.)
            # Chovani: ponechame; starsi labels z mezery vynulujeme.
            self.conn.execute("DELETE FROM labels")

    # --- utility ----------------------------------------------------------
    def close(self) -> None:
        try:
            if self.trees_db_path is not None:
                self.conn.execute("DETACH DATABASE trees_db")
        except sqlite3.Error:
            pass
        self.conn.close()

    @staticmethod
    def parse_section_id(filename: str) -> int | None:
        """'cloud_segmented_123.laz' -> 123; 'cloud_segmented_-1.laz' -> -1; jinak None."""
        m = re.search(r"_(-?\d+)\.(laz|las)$", filename.lower())
        return int(m.group(1)) if m else None

    def get_tree_meta(self, section_id: int) -> dict | None:
        return (self._trees or {}).get(section_id)

    def verify_pairing(self, laz_names: list[str]) -> dict:
        """Overeni parovani: LAZ soubory <-> tabulka trees pres section_id/tree_id."""
        known = []
        orphan_trees = []
        new_trees = []
        unparsable = []
        db_ids = set((self._trees or {}).keys())
        laz_ids = set()
        for name in laz_names:
            sid = self.parse_section_id(name)
            if sid is None:
                unparsable.append(name)
                continue
            if sid == -1:
                continue  # vyhrazeny soubor okoli — striktne preskocen
            laz_ids.add(sid)
            if sid in db_ids:
                known.append(sid)
            else:
                new_trees.append(sid)
        for sid in sorted(db_ids):
            if sid not in laz_ids:
                orphan_trees.append(sid)
        return {
            "known": known, "orphan_trees": orphan_trees,
            "new_trees": new_trees, "unparsable": unparsable,
            "total_laz": len(laz_ids), "total_trees": len(db_ids),
        }

    # --- files ------------------------------------------------------------
    def upsert_file(self, path: Path, n_points: int | None) -> int:
        """Registruje soubor s tree_id z jeho jmena a vrati tree_id.
        Pokud jiz existuje zaznam s timto tree_id (kdekoliv), aktualizuje
        abs_path (relocation) a n_points — sjednoceni pri dalsi nahravce."""
        tid = self.parse_section_id(path.name)
        if tid == -1:
            raise ValueError(f"cloud_segmented_-1 nesmi vstoupit do analyzy: {path}")
        if tid is None:
            raise ValueError(f"cloud_segmented_* filename bez cisla: {path.name}")
        # 1) existuje abs_path → jen aktualizuj n_points
        cur = self.conn.execute(
            "SELECT tree_id FROM files WHERE abs_path = ?", (str(path.resolve()),)
        )
        row = cur.fetchone()
        if row:
            if n_points is not None:
                self.conn.execute(
                    "UPDATE files SET n_points = ? WHERE tree_id = ?",
                    (n_points, row["tree_id"]),
                )
                self.conn.commit()
            return row["tree_id"]
        # 2) existuje tree_id jinde (soubor se presel) → update relocation
        cur = self.conn.execute(
            "SELECT tree_id FROM files WHERE tree_id = ?", (tid,)
        )
        row = cur.fetchone()
        if row:
            self.conn.execute(
                "UPDATE files SET filename = ?, abs_path = ?, n_points = COALESCE(?, n_points) WHERE tree_id = ?",
                (path.name, str(path.resolve()), n_points, tid),
            )
            self.conn.commit()
            return tid
        # 3) novy zaznam
        self.conn.execute(
            "INSERT INTO files (tree_id, filename, abs_path, n_points, imported_at) VALUES (?,?,?,?,?)",
            (tid, path.name, str(path.resolve()), n_points, _now()),
        )
        self.conn.commit()
        return tid

    def set_bbox(self, tree_id: int, bbox: tuple[float, float, float, float, float, float]) -> None:
        """Zapise XYZ bbox stromu: (x_min, x_max, y_min, y_max, z_min, z_max)."""
        x0, x1, y0, y1, z0, z1 = bbox
        self.conn.execute(
            "UPDATE files SET x_min=?, x_max=?, y_min=?, y_max=?, z_min=?, z_max=? WHERE tree_id=?",
            (x0, x1, y0, y1, z0, z1, tree_id),
        )
        self.conn.commit()

    def get_bbox(self, tree_id: int) -> tuple | None:
        row = self.conn.execute(
            "SELECT x_min, x_max, y_min, y_max, z_min, z_max FROM files WHERE tree_id=?",
            (tree_id,),
        ).fetchone()
        if not row:
            return None
        if row["x_min"] is None or row["y_min"] is None or row["z_min"] is None:
            return None
        return (row["x_min"], row["x_max"], row["y_min"], row["y_max"], row["z_min"], row["z_max"])

    def get_file_path(self, tree_id: int) -> Path | None:
        """Vrati absolutni cestu k souboru daneho stromu (podle filename ulozeneho
        v DB pri scanu). Vrati None pokud soubor neexistuje."""
        row = self.conn.execute(
            "SELECT abs_path FROM files WHERE tree_id = ?", (tree_id,)
        ).fetchone()
        if not row:
            return None
        p = Path(row["abs_path"])
        return p if p.exists() else None

    def get_neighbors(self, tree_id: int, buffer: float = 1.0) -> list[int]:
        """ID stromu, jejichz MRIZKA (pavodni bbox) intersectuje s bbox targetu
        rozsirenym o buffer (jen XY rovina). Pouziva se pro context volbu.
        Pozor: strom sam je vzdy exclude (-1)."""
        t = self.get_bbox(tree_id)
        if not t:
            return []
        tx0, tx1, ty0, ty1, _tz0, _tz1 = t
        rows = self.conn.execute(
            """SELECT tree_id, x_min, x_max, y_min, y_max FROM files
               WHERE tree_id != ? AND x_min IS NOT NULL""",
            (tree_id,),
        ).fetchall()
        result = []
        for r in rows:
            if r["tree_id"] == -1:
                continue
            if not (r["x_max"] < tx0 - buffer or r["x_min"] > tx1 + buffer or
                    r["y_max"] < ty0 - buffer or r["y_min"] > ty1 + buffer):
                result.append(r["tree_id"])
        return result

    def list_files(self) -> list[dict]:
        rows = self._query_files()
        if self.external:
            for r in rows:
                meta = self.get_tree_meta(r["tree_id"]) if r["tree_id"] is not None else None
                r["section_id"] = r["tree_id"]        # alias pro klienty
                r["dist2dmt"] = (meta or {}).get("dist2dmt")
        return rows

    def _query_files(self) -> list[dict]:
        cur = self.conn.execute(
            """
            SELECT f.tree_id AS id, f.tree_id, f.filename, f.abs_path, f.n_points,
                   c1.name AS tree_type,
                   c2.name AS quality
            FROM files f
            LEFT JOIN labels l  ON l.tree_id = f.tree_id
            LEFT JOIN categories c1 ON c1.id = l.category_id
            LEFT JOIN categories c2 ON c2.id = l.quality_category_id
            ORDER BY f.tree_id
            """
        )
        # vracime id jako legacy alias tree_id (klient jiz pracuje s "id")
        return [dict(r) for r in cur.fetchall()]

    def get_file(self, file_id: int) -> dict | None:
        cur = self.conn.execute(
            """
            SELECT f.tree_id AS id, f.tree_id, f.filename, f.abs_path, f.n_points,
                   c1.name AS tree_type, c1.id AS tree_type_id,
                   c2.name AS quality,  c2.id AS quality_id
            FROM files f
            LEFT JOIN labels l  ON l.tree_id = f.tree_id
            LEFT JOIN categories c1 ON c1.id = l.category_id
            LEFT JOIN categories c2 ON c2.id = l.quality_category_id
            WHERE f.tree_id = ?
            """,
            (file_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        rec = dict(row)
        if self.external:
            meta = self.get_tree_meta(rec["tree_id"]) if rec["tree_id"] is not None else None
            rec["section_id"] = rec["tree_id"]
            rec["dist2dmt"] = (meta or {}).get("dist2dmt")
        return rec

    # --- categories -------------------------------------------------------
    def sync_categories(self, categories: list[dict]) -> None:
        yaml_names = {c["name"] for c in categories}
        stale = self.conn.execute("SELECT id, name FROM categories").fetchall()
        for row in stale:
            if row["name"] not in yaml_names:
                refs = self.conn.execute(
                    "SELECT COUNT(*) AS n FROM labels WHERE category_id=? OR quality_category_id=?",
                    (row["id"], row["id"]),
                ).fetchone()["n"]
                if refs == 0:
                    self.conn.execute("DELETE FROM categories WHERE id=?", (row["id"],))

        for cat in categories:
            self.conn.execute(
                """
                INSERT INTO categories (name, grp, shortcut, description, created_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                  grp = excluded.grp,
                  shortcut = excluded.shortcut,
                  description = excluded.description
                """,
                (
                    cat["name"],
                    cat.get("group") or cat.get("grp"),
                    cat.get("shortcut"),
                    cat.get("description"),
                    _now(),
                ),
            )
        self.conn.commit()

    def list_categories(self) -> list[dict]:
        cur = self.conn.execute(
            'SELECT id, name, grp AS "group", shortcut, description FROM categories ORDER BY id'
        )
        return [dict(r) for r in cur.fetchall()]

    def get_category_id(self, name: str) -> int | None:
        cur = self.conn.execute("SELECT id FROM categories WHERE name = ?", (name,))
        row = cur.fetchone()
        return row["id"] if row else None

    # --- labels -----------------------------------------------------------
    def set_label(
        self,
        tree_id: int,
        tree_type: str | None = None,
        quality: str | None = None,
        note: str | None = None,
    ) -> None:
        """Ulozi label podle tree_id. tree_type a quality jsou nezavisle."""
        tt_id = self.get_category_id(tree_type) if tree_type else None
        q_id = self.get_category_id(quality) if quality else None
        if tree_type and tt_id is None:
            raise ValueError(f"Neznama kategorie: {tree_type}")
        if quality and q_id is None:
            raise ValueError(f"Neznama kategorie: {quality}")
        if tt_id is None and q_id is None:
            raise ValueError("Nic k ulozeni")

        existing = self.conn.execute(
            "SELECT category_id, quality_category_id FROM labels WHERE tree_id = ?",
            (tree_id,),
        ).fetchone()
        if existing:
            new_tt = tt_id if tt_id is not None else existing["category_id"]
            new_q = q_id if q_id is not None else existing["quality_category_id"]
            self.conn.execute(
                "UPDATE labels SET category_id=?, quality_category_id=?, labeled_at=?, note=? WHERE tree_id=?",
                (new_tt, new_q, _now(), note, tree_id),
            )
        else:
            self.conn.execute(
                "INSERT INTO labels (tree_id, category_id, quality_category_id, labeled_at, note) VALUES (?,?,?,?,?)",
                (tree_id, tt_id, q_id, _now(), note),
            )
        self.conn.commit()

    def next_unlabeled_id(self) -> int | None:
        cur = self.conn.execute(
            """
            SELECT f.tree_id FROM files f
            LEFT JOIN labels l ON l.tree_id = f.tree_id
            LEFT JOIN categories c ON c.id = l.category_id
            WHERE l.tree_id IS NULL
               OR (c.name = 'Not a tree') IS NOT TRUE
               AND (l.category_id IS NULL OR l.quality_category_id IS NULL)
            ORDER BY f.tree_id
            LIMIT 1
            """
        )
        row = cur.fetchone()
        return row["tree_id"] if row else None

    def progress(self) -> dict:
        cur = self.conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN c.name = 'Not a tree' THEN 1
                            WHEN l.category_id IS NOT NULL
                             AND l.quality_category_id IS NOT NULL
                        THEN 1 ELSE 0 END) AS labeled
            FROM files f
            LEFT JOIN labels l ON l.tree_id = f.tree_id
            LEFT JOIN categories c ON c.id = l.category_id
            """
        )
        row = cur.fetchone()
        return {"total": row["total"], "labeled": row["labeled"] or 0}
