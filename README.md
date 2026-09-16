# TreeLabeler

Standalone desktop application for **manual labeling of tree point clouds** (LAZ/LAS, one tree per file). FastAPI backend, three.js viewer, SQLite persistence. Developed at VUKOZ for forestry LiDAR workflows. Portable exe distribution via PyInstaller — no Python or dependencies required on the target machine.

![workflow](docs/images/workflow.png)

## Features

- 3D point-cloud viewer with rotation, zoom, and measurement aspects:
  - 3×3 m measurement grid at the tree's lowest point, with `dist2dmt` vertical correction from external SQLite (raycloudtools)
  - Color-coded points by label status (pending → tree_type × quality)
  - Point size scaled to tree extent
- Fully keyboard-driven labeling: Q W E (species), A S D F (segmentation), Space = skip
  - Auto-advance to the next unlabeled tree once both categories are filled
  - Auto-skip of `cloud_segmented_-1.laz` (background file, kept strictly out of analysis)
- **Context overlay (key `C` / button)**: shows surrounding trees' points (olive) and ground-level background (grey) clipped to the target tree's footprint + 1 m buffer. Neighbors are identified by bounding-box intersection from a scan-time bbox index.
- External **raycloudtools SQLite integration** (table `trees` with `section_id`):
  - Automatic pairing of LAZ files to tree records via filename
  - `tree_id` aliases both in `files` and `labels` tables
  - Labels are written directly to the writable sqlite (no intermediate copy)
  - Immutable `source_data/` folders are redirected to a working copy automatically
- Cross-tree label persistence in SQLite; CSV export for downstream tools

## Quick start (portable exe)

1. Copy `outputs/treelabeler.exe` to your machine.
2. Run it — GUI opens on `http://127.0.0.1:8000`.
3. Paste the data folder path into the input box and click **Load**.
4. Label with keyboard shortcuts (see below); Space or Next to skip.

### Keyboard map

| Key | Action |
|-----|--------|
| Q / W / E | SPECIES: Broadleaf / Coniferous / Not a tree |
| A / S / D / F | SEGMENTATION: Complete / Missing part / Excessive part / Multitree |
| C | Toggle surrounding context points (neighbors + background) |
| Space | Save & next unlabeled tree |

## Data requirements

- Folder with `cloud_segmented_<number>.laz` files (one per tree).
- Optional `cloud_segmented_-1.laz` — background points used as the context overlay. Never processed as a tree.
- Optional `<scene>.laz.sqlite` (raycloudtools) with a `trees` table including `section_id` and `dist2dmt` columns. If present and writable, labels are persisted there directly.

## Build from source

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt

# run
set PYTHONPATH=src
python -m treelabeler data/your_folder
```

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q      # 26 tests
```

### Portable exe (PyInstaller)

```bash
pip install pyinstaller
pyinstaller --clean --noconfirm treelabeler.spec
# output → dist/treelabeler.exe  (move to outputs/ for distribution)
```

## Repository layout

```
src/treelabeler/       FastAPI app (db, loader, server) + static web GUI
tests/                  test suite (26 tests)
tools/                  PyInstaller entry point (launcher.py)
outputs/treelabeler.exe prebuilt binary (Windows x64)
.github/workflows/     CI (tests + exe build, if enabled)
treelabeler.spec       PyInstaller build definition
run.bat                 Windows dev launcher
requirements*.txt      dependencies
```

## License

MIT — see LICENSE.
