"""Download League of Legends icons (champion spells, summoners, items) from
Riot Data Dragon CDN into ``resources/``.

DDragon is a public CDN — no API key required. Skips any file that already
exists, so the script is safe to re-run after the LoL patch bumps versions.

Usage:
    python tools/download_ddragon.py            # latest version, ko_KR locale
    python tools/download_ddragon.py --locale en_US
    python tools/download_ddragon.py --version 14.18.1
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / 'resources'

VERSIONS_URL = 'https://ddragon.leagueoflegends.com/api/versions.json'

# CommunityDragon mirrors the in-game asset bundle, which includes recast /
# stance-change icons that DDragon's spells[] never exposes (LeeSinQ2, RivenR2,
# etc). We discover them per-champion by scanning the character bin.json.
CDRAGON_BASE = 'https://raw.communitydragon.org/latest'
CDRAGON_HEADERS = {'User-Agent': 'Mozilla/5.0'}
_ICON_REF_RE = re.compile(
    r'"ASSETS/Characters/[^/"]+/HUD/Icons2D/([A-Za-z][A-Za-z0-9_]*)\.dds"',
    re.IGNORECASE,
)
_ORDINAL_WORD_TO_DIGIT = {'one': '1', 'two': '2', 'three': '3', 'four': '4'}
_ORDINAL_TAIL_RE = re.compile(r'(One|Two|Three|Four)$', re.IGNORECASE)


def fetch_json(url, retries=3):
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError) as exc:
            if i == retries - 1:
                raise
            time.sleep(1 + i)


def download(url, dst, retries=3):
    """Download url -> dst. Skips if dst already exists. Returns True if newly written."""
    dst = Path(dst)
    if dst.exists() and dst.stat().st_size > 0:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read()
            tmp = dst.with_suffix(dst.suffix + '.part')
            tmp.write_bytes(data)
            tmp.replace(dst)
            return True
        except (urllib.error.URLError, TimeoutError) as exc:
            if i == retries - 1:
                print(f'  ! failed: {url}: {exc}', file=sys.stderr)
                return False
            time.sleep(1 + i)


def try_download_silent(url, dst, headers=None):
    """Single-attempt download for assets that may not exist.
    Returns True if file exists locally after the attempt."""
    dst = Path(dst)
    if dst.exists() and dst.stat().st_size > 0:
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
    except Exception:
        return False
    tmp = dst.with_suffix(dst.suffix + '.part')
    tmp.write_bytes(data)
    tmp.replace(dst)
    return True


def _normalize_spell_stem(stem):
    """Canonicalize trailing ordinal so 'LeeSinQOne' and 'LeeSinQ1' compare equal,
    but 'LeeSinQ2' stays distinct."""
    m = _ORDINAL_TAIL_RE.search(stem)
    if m:
        stem = stem[: m.start()] + _ORDINAL_WORD_TO_DIGIT[m.group(1).lower()]
    return stem.lower()


def cdragon_extra_spell_icons(champ_id, primary_stems):
    """Discover non-primary spell icons on CommunityDragon for a champion.

    Returns list of (icon_id, png_url, slot_letter). slot_letter is Q/W/E/R
    when derivable from the icon id, otherwise None. ``primary_stems`` is the
    set of normalized stems already covered by DDragon (skip them).
    """
    champ_lower = champ_id.lower()
    bin_url = f'{CDRAGON_BASE}/game/data/characters/{champ_lower}/{champ_lower}.bin.json'
    req = urllib.request.Request(bin_url, headers=CDRAGON_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read().decode('utf-8', errors='replace')
    except Exception:
        return []

    seen = set()
    out = []
    for m in _ICON_REF_RE.finditer(text):
        icon_id = m.group(1)
        key = icon_id.lower()
        if key in seen:
            continue
        seen.add(key)
        if _normalize_spell_stem(icon_id) in primary_stems:
            continue
        # slot letter: first char after champion id, if it is Q/W/E/R
        slot = None
        if key.startswith(champ_lower) and len(key) > len(champ_lower):
            c = key[len(champ_lower)].upper()
            if c in ('Q', 'W', 'E', 'R'):
                slot = c
        png_url = f'{CDRAGON_BASE}/game/assets/characters/{champ_lower}/hud/icons2d/{key}.png'
        out.append((icon_id, png_url, slot))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--locale', default='ko_KR')
    ap.add_argument('--version', default=None,
                    help='Override DDragon version (default: latest)')
    args = ap.parse_args()

    if args.version:
        version = args.version
    else:
        versions = fetch_json(VERSIONS_URL)
        version = versions[0]
    print(f'DDragon version: {version}, locale: {args.locale}')
    base = f'https://ddragon.leagueoflegends.com/cdn/{version}'

    RES.mkdir(parents=True, exist_ok=True)
    (RES / 'version.txt').write_text(version, encoding='utf-8')

    # ----- champions list (summary) -----
    champ_summary = fetch_json(f'{base}/data/{args.locale}/champion.json')['data']
    print(f'champions: {len(champ_summary)}')

    manifest = {
        'version': version,
        'locale': args.locale,
        'champions': {},
        'summoners': {},
        'items': {},
    }

    new_files = 0
    total_files = 0

    # ----- per-champion: portrait + Q/W/E/R + passive -----
    for idx, champ_id in enumerate(sorted(champ_summary.keys()), start=1):
        info = champ_summary[champ_id]
        ko_name = info.get('name', champ_id)

        portrait_url = f'{base}/img/champion/{champ_id}.png'
        portrait_dst = RES / 'champion' / 'icons' / f'{champ_id}.png'
        total_files += 1
        if download(portrait_url, portrait_dst):
            new_files += 1

        detail = fetch_json(f'{base}/data/{args.locale}/champion/{champ_id}.json')['data'][champ_id]

        spells_meta = []
        primary_stems = set()
        for slot, spell in zip(['Q', 'W', 'E', 'R'], detail['spells']):
            fname = spell['image']['full']
            url = f'{base}/img/spell/{fname}'
            dst = RES / 'champion' / 'spells' / fname
            total_files += 1
            if download(url, dst):
                new_files += 1
            primary_stems.add(_normalize_spell_stem(Path(fname).stem))
            spells_meta.append({
                'key': slot,
                'name': spell['name'],
                'icon': str(dst.relative_to(RES)).replace('\\', '/'),
            })

        # recast / stance-change icons via CommunityDragon (LeeSinQ2 etc.)
        for icon_id, alt_url, slot in cdragon_extra_spell_icons(champ_id, primary_stems):
            if slot is None:
                continue  # passive variants etc — no slot to attach
            alt_dst = RES / 'champion' / 'spells' / f'{icon_id}.png'
            already = alt_dst.exists() and alt_dst.stat().st_size > 0
            total_files += 1
            if not try_download_silent(alt_url, alt_dst, headers=CDRAGON_HEADERS):
                continue
            if not already:
                new_files += 1
            rel = str(alt_dst.relative_to(RES)).replace('\\', '/')
            target = next((e for e in spells_meta if e['key'] == slot), None)
            if target is not None:
                target.setdefault('alts', []).append({'icon': rel})

        passive_fname = detail['passive']['image']['full']
        url = f'{base}/img/passive/{passive_fname}'
        dst = RES / 'champion' / 'passives' / passive_fname
        total_files += 1
        if download(url, dst):
            new_files += 1
        passive_meta = {
            'name': detail['passive']['name'],
            'icon': str(dst.relative_to(RES)).replace('\\', '/'),
        }

        manifest['champions'][champ_id] = {
            'name_localized': ko_name,
            'portrait': str(portrait_dst.relative_to(RES)).replace('\\', '/'),
            'spells': spells_meta,
            'passive': passive_meta,
        }

        if idx % 10 == 0 or idx == len(champ_summary):
            print(f'  {idx}/{len(champ_summary)} champions  ({new_files} new files)')

    # ----- summoner spells -----
    summoners = fetch_json(f'{base}/data/{args.locale}/summoner.json')['data']
    print(f'summoner spells: {len(summoners)}')
    for sid, summ in summoners.items():
        fname = summ['image']['full']
        url = f'{base}/img/spell/{fname}'
        dst = RES / 'summoner' / fname
        total_files += 1
        if download(url, dst):
            new_files += 1
        manifest['summoners'][sid] = {
            'name': summ['name'],
            'icon': str(dst.relative_to(RES)).replace('\\', '/'),
        }

    # ----- items -----
    items = fetch_json(f'{base}/data/{args.locale}/item.json')['data']
    print(f'items: {len(items)}')
    for item_id, item in items.items():
        fname = item['image']['full']
        url = f'{base}/img/item/{fname}'
        dst = RES / 'item' / fname
        total_files += 1
        if download(url, dst):
            new_files += 1
        manifest['items'][item_id] = {
            'name': item['name'],
            'icon': str(dst.relative_to(RES)).replace('\\', '/'),
        }

    # ----- write manifest -----
    (RES / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    print()
    print(f'done. wrote {new_files} new files (total checked: {total_files}).')
    print(f'output: {RES}')


if __name__ == '__main__':
    main()
