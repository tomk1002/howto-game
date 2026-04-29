"""Lazy loader for the DDragon manifest at ``resources/manifest.json``.

Functions in this module return empty / None gracefully when the
resource bundle hasn't been downloaded yet, so the rest of the app can
treat icons as a soft enhancement rather than a hard dependency.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt6.QtGui import QPixmap

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_DIR = PROJECT_ROOT / 'resources'
MANIFEST_PATH = RESOURCES_DIR / 'manifest.json'


def path_to_relative(path):
    """If path is inside PROJECT_ROOT, return forward-slash relative path.
    Otherwise return the path unchanged."""
    if not path:
        return path
    try:
        rel = Path(path).resolve().relative_to(PROJECT_ROOT.resolve())
        return rel.as_posix()
    except (ValueError, OSError):
        return path


def path_to_absolute(path):
    """Resolve a possibly-relative path against PROJECT_ROOT."""
    if not path:
        return path
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str((PROJECT_ROOT / p).resolve())

_manifest_cache = None
_pixmap_cache: Dict[str, QPixmap] = {}


def load_manifest() -> Optional[dict]:
    global _manifest_cache
    if _manifest_cache is not None:
        return _manifest_cache
    if not MANIFEST_PATH.exists():
        return None
    try:
        _manifest_cache = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    except Exception:
        return None
    return _manifest_cache


def manifest_available() -> bool:
    return load_manifest() is not None


def champion_choices() -> List[Tuple[str, str]]:
    """Sorted list of (localized name, champion_id). Empty if no manifest."""
    m = load_manifest()
    if not m:
        return []
    champs = m.get('champions', {})
    return sorted(
        [(info.get('name_localized', cid), cid) for cid, info in champs.items()],
        key=lambda kv: kv[0],
    )


def _load_pixmap(rel_path: str) -> Optional[QPixmap]:
    if not rel_path:
        return None
    cached = _pixmap_cache.get(rel_path)
    if cached is not None:
        return cached
    full = RESOURCES_DIR / rel_path
    if not full.exists():
        return None
    pix = QPixmap(str(full))
    if pix.isNull():
        return None
    _pixmap_cache[rel_path] = pix
    return pix


def champion_skill_icons(champion_id: str) -> Dict[str, QPixmap]:
    """Returns {'Q': QPixmap, 'W': QPixmap, 'E': QPixmap, 'R': QPixmap}.

    Missing icons silently omitted. Empty dict if champion unknown.
    """
    if not champion_id:
        return {}
    m = load_manifest()
    if not m:
        return {}
    champ = m.get('champions', {}).get(champion_id)
    if not champ:
        return {}
    out = {}
    for spell in champ.get('spells', []):
        slot = spell.get('key')
        pix = _load_pixmap(spell.get('icon'))
        if slot and pix:
            out[slot] = pix
    return out


def champion_portrait(champion_id: str) -> Optional[QPixmap]:
    if not champion_id:
        return None
    m = load_manifest()
    if not m:
        return None
    champ = m.get('champions', {}).get(champion_id)
    if not champ:
        return None
    return _load_pixmap(champ.get('portrait'))
