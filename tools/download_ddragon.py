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
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / 'resources'

VERSIONS_URL = 'https://ddragon.leagueoflegends.com/api/versions.json'


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
        for slot, spell in zip(['Q', 'W', 'E', 'R'], detail['spells']):
            fname = spell['image']['full']
            url = f'{base}/img/spell/{fname}'
            dst = RES / 'champion' / 'spells' / fname
            total_files += 1
            if download(url, dst):
                new_files += 1
            spells_meta.append({
                'key': slot,
                'name': spell['name'],
                'icon': str(dst.relative_to(RES)).replace('\\', '/'),
            })

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
