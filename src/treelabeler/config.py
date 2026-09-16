"""Konfigurace aplikace (kategorie nadrǎdeně v kodu)."""

from __future__ import annotations

from pathlib import Path


DEFAULT_CATEGORIES = {
    "groups": [
        {"id": "tree_type", "label": "SPECIES"},
        {"id": "quality", "label": "SEGMENTATION"},
    ],
    "categories": [
        {"name": "Broadleaf", "group": "tree_type", "shortcut": "q", "description": "Deciduous tree"},
        {"name": "Coniferous", "group": "tree_type", "shortcut": "w", "description": "Conifer tree"},
        {"name": "Not a tree", "group": "tree_type", "shortcut": "e", "description": "Segment is not a tree"},
        {"name": "Complete", "group": "quality", "shortcut": "a", "description": "Complete tree segmentation"},
        {"name": "Missing part", "group": "quality", "shortcut": "s", "description": "Part of the crown/tree is missing"},
        {"name": "Excessive part", "group": "quality", "shortcut": "d", "description": "Extra part (neighbor crown, branches)"},
        {"name": "Multitree", "group": "quality", "shortcut": "f", "description": "File contains 2+ trees"},
    ],
}


def load_categories(config_path: Path | None = None) -> dict:
    """Vrati konfiguraci kategorii. V aktualni verzi zanedbavame YAML davame defaultni."""
    return DEFAULT_CATEGORIES


def project_config_path() -> Path:
    """Vychozi cesta ke categories.yaml — pouziva se jen pro fallback dev nacitani."""
    p = Path.cwd() / "config" / "categories.yaml"
    return p
