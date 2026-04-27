import json
from datetime import datetime, timezone
from pathlib import Path

FORMAT_VERSION = 1


def save(events, path, *, title='', game='', tags=None):
    """Save events to a JSON file using the standard HowTo format."""
    duration_ms = max((e.get('t_ms', 0) for e in events), default=0)
    data = {
        'version': FORMAT_VERSION,
        'title': title,
        'game': game,
        'tags': list(tags or []),
        'duration_ms': duration_ms,
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'events': list(events),
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def load(path):
    """Load a HowTo JSON file. Returns the parsed dict."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict) or 'events' not in data:
        raise ValueError(f"invalid HowTo file: {path}")
    return data
