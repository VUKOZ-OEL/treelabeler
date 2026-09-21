"""Nacitani LAS/LAZ bodovych mracen."""

from __future__ import annotations

from pathlib import Path

import laspy
import numpy as np


def load_points(path: Path) -> dict:
    """Nacte mračno a vrati pozice + RGB v numpy polich.

    Vraci slovnik:
      - path, n_points
      - positions: float32 (N,3) — X,Y,Z
      - colors: uint8 (N,3) — RGB (z barev, jinak odvozene z vysky Z)
    """
    las = laspy.read(str(path))
    # float64 kvuli presnosti — S-JTSK ma souradnice ~4.8M / 2.9M, float32 ztraci desetinna mista
    positions = np.vstack([las.x, las.y, las.z]).T.astype(np.float64)

    colors = None
    try:
        if all(hasattr(las, c) for c in ("red", "green", "blue")):
            rgb = np.vstack([las.red, las.green, las.blue]).T
            if rgb.dtype != np.uint8:
                maxv = int(rgb.max()) if rgb.size else 0
                if maxv > 255:
                    scale = 65535.0 / 255.0
                    rgb = np.clip(rgb / scale, 0, 255).astype(np.uint8)
                else:
                    rgb = rgb.astype(np.uint8)
            colors = rgb
    except Exception:
        colors = None

    if colors is None:
        z = positions[:, 2]
        zmin, zmax = float(z.min()), float(z.max())
        rng = (zmax - zmin) if zmax > zmin else 1.0
        t = ((z - zmin) / rng).astype(np.float32)
        # jednoduchy colormap: zelena -> hneda (nizke->vysoke)
        colors = np.zeros((len(z), 3), dtype=np.uint8)
        colors[:, 0] = np.uint8(np.clip(80 + 120 * t, 0, 255))       # R
        colors[:, 1] = np.uint8(np.clip(140 - 40 * t, 0, 255))      # G
        colors[:, 2] = np.uint8(np.clip(60 - 30 * t, 0, 255))       # B

    origin = [float(positions[0, 0]), float(positions[0, 1]), float(positions[0, 2])]

    return {
        "path": str(path),
        "n_points": len(positions),
        "positions": positions,   # float64 — presnost zachovana
        "colors": colors,
        "origin": origin,         # pivot pro centrované renderování (velka cisla S-JTSK)
    }

def load_bbox_index(data_dir, db) -> dict:
    """Projde vsechny LAZ ve slozce (trechni bez -1), ulozi bbox do DB.
    Optimalizace: cte LAZ hlavicky (header) — ne zaznamy — skoro zadarmo.
    Vrati slovnik {tree_id: (x0, x1, y0, y1, z0, z1)}; liny klic 'target'.
    """
    import laspy as _lp
    found = {}
    for f in sorted(data_dir.iterdir()):
        if f.suffix.lower() not in (".las", ".laz"):
            continue
        sid = db.parse_section_id(f.name)
        if sid is None or sid == -1:
            continue
        try:
            las = _lp.read(str(f))
            x, y, z = np.asarray(las.x), np.asarray(las.y), np.asarray(las.z)
            bbox = (float(x.min()), float(x.max()),
                    float(y.min()), float(y.max()),
                    float(z.min()), float(z.max()))
            db.set_bbox(sid, bbox)
            found[sid] = bbox
        except Exception:
            continue
    return found


def load_context_for_tree(
    db,
    data_dir,
    tree_id: int,
    buffer: float = 1.0,
    max_points: int = 800_000,
    seed: int = 42,
    tree_origin: tuple[float, float, float] | None = None,
) -> dict | None:
    """Body okoli stromu `tree_id`.

    Vybir:
      - target bbox stromu rozsireny o `buffer` (napr. 1m) — do nej bereme body,
        - sousedni stromy (AABB v XY roviny se prekryva s targetem + buffer):
          bereme JEJICH uplny bbox (bez bufferu — samotny strom),
        - soubor -1 (okoli): ohranicime na target bbox + buffer (ne cely scene),
    Vraci slovnik:
      {
        "tree_origin": (ox,oy,oz),
        "segments": [ {tree_id, n, positions(float64)}, ... ],
        "background": {"n", "positions"} | None,
        "neighbors": [ids],
      }
    """
    target = db.get_bbox(tree_id)
    neighbors = db.get_neighbors(tree_id, buffer=buffer) if target else []

    # klipove okno pro vse: target bbox + buffer v XY (Z neomezujeme —
    # koruny sousedi mohou presahovat nad bbox targetu).
    tx0 = tx1 = ty0 = ty1 = None
    if target:
        tx0, tx1, ty0, ty1 = target[0], target[1], target[2], target[3]

    segments = []
    for nid in neighbors:
        p = db.get_file_path(nid)
        if p is None:
            continue
        las = laspy.read(str(p))
        x = np.asarray(las.x, dtype=np.float64)
        y = np.asarray(las.y, dtype=np.float64)
        z = np.asarray(las.z, dtype=np.float64)
        nb = db.get_bbox(nid)
        # pokud neni bbox souseda KOMPLETNE uvnitr target+buffer okna, orezeme
        # jeho body na toto oken (jinak maska = vlastni bbox = nic neodreze)
        if nb and target:
            fully_inside = (
                nb[0] >= tx0 - buffer and nb[1] <= tx1 + buffer and
                nb[2] >= ty0 - buffer and nb[3] <= ty1 + buffer
            )
            if not fully_inside:
                m = np.logical_and.reduce([
                    x >= tx0 - buffer, x <= tx1 + buffer,
                    y >= ty0 - buffer, y <= ty1 + buffer,
                ])
                x, y, z = x[m], y[m], z[m]
        if len(x):
            segments.append({
                "tree_id": nid,
                "n": int(len(x)),
                "positions": np.column_stack([x, y, z]),
            })

    background = None
    bg_path = None
    for cand in data_dir.iterdir():
        if db.parse_section_id(cand.name) == -1 and cand.suffix.lower() in (".laz", ".las"):
            bg_path = cand
            break
    if bg_path is not None and target:
        las = laspy.read(str(bg_path))
        x = np.asarray(las.x, dtype=np.float64)
        y = np.asarray(las.y, dtype=np.float64)
        z = np.asarray(las.z, dtype=np.float64)
        tx0, tx1, ty0, ty1, tz0, tz1 = target
        m = np.logical_and.reduce([
            x >= tx0 - buffer, x <= tx1 + buffer,
            y >= ty0 - buffer, y <= ty1 + buffer,
        ])
        x, y, z = x[m], y[m], z[m]
        if len(x):
            background = {"n": int(len(x)), "positions": np.column_stack([x, y, z])}

    if not segments and background is None:
        return None
    return {
        "target_bbox": target,
        "buffer": buffer,
        "neighbors": neighbors,
        "segments": segments,
        "background": background,
    }

