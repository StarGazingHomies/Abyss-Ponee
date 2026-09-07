"""One-shot generator for the achievement assets and metadata table.

Downloads the medal frames and note badges from the TETR.IO resource server,
slices the achievement icon sprite sheets into one PNG per achievement, and
writes ``achievements.json`` (used only to back the
``/teto_achievements`` autocomplete).

Run it by hand after a TETR.IO update adds achievements; the bot never calls it.

    python tools/fetch_achievements.py [--user-agent UA] [--force]
"""
import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

from PIL import Image

ROOT = pathlib.Path(__file__).parent.parent
ASSETS = ROOT / "assets" / "achievements"
CONFIG_PATH = ROOT / "config.json"

RES_URL = "https://tetr.io/res/achievements"
API_URL = "https://ch.tetr.io/api/achievements"

K_MAX = 67                     # highest achievement ID to probe; gaps are skipped
SPRITE = 256                   # one sprite is 256x256 in a 2048x2048 (8x8) sheet
SHEET_COLS = 8
SHEET_SPRITES = 64

FRAMES = ('none', 'bronze', 'silver', 'gold', 'platinum', 'diamond', 'issued')
BADGES = ('competitive', 'unranked', 'hidden', 'event', 'disabled')

# The fields render/achievements.py and the autocomplete actually read. The
# renderer always uses the live API response, so this table only has to be good
# enough to find an achievement by name.
META_FIELDS = ('k', 'name', 'category', 'object', 'desc', 'rt', 'vt', 'art',
               'min', 'deci', 'hidden', 'nolb', 'pair', 'disabled', 'event', 'event_past')


def _user_agent(override=None):
    if override:
        return override
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            ua = (json.load(f).get('headers') or {}).get('User-Agent')
    except (OSError, ValueError):
        ua = None
    if not ua:
        sys.exit(f"No User-Agent in {CONFIG_PATH}; pass --user-agent. TETR.IO rejects default ones.")
    return ua


def _get(url, ua):
    req = urllib.request.Request(url, headers={'User-Agent': ua})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _download(url, dest, ua, force=False):
    if dest.exists() and not force:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_get(url, ua))
    return True


def fetch_images(ua, force=False):
    n = 0
    for name in FRAMES:
        n += _download(f"{RES_URL}/frames/{name}.png", ASSETS / "frames" / f"{name}.png", ua, force)
    for name in BADGES:
        n += _download(f"{RES_URL}/{name}.png", ASSETS / "badges" / f"{name}.png", ua, force)
    print(f"frames/badges: {n} downloaded, "
          f"{len(FRAMES) + len(BADGES) - n} already present")


def slice_icons(ks, ua, force=False):
    """Cut assets/achievements/icons/{k}.png out of the sprite sheets.

    The sheets are 8x8 grids of 256px sprites; achievement *k* lives at index
    ``(k - 1) % 64`` of sheet ``(k - 1) // 64``. The sprites are white
    silhouettes -- the renderer inverts them, matching TETRA CHANNEL's
    ``filter: invert(1)``."""
    out_dir = ASSETS / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)
    sheets = {}
    written = 0
    for k in ks:
        dest = out_dir / f"{k}.png"
        if dest.exists() and not force:
            continue
        s = (k - 1) // SHEET_SPRITES
        if s not in sheets:
            raw = ROOT / "assets" / "achievements" / f"_sheet_{s}.png"
            _download(f"{RES_URL}/icons/{s}.png", raw, ua, force)
            sheets[s] = Image.open(raw).convert("RGBA")   # icons/1.png ships as palette mode
        idx = (k - 1) % SHEET_SPRITES
        col, row = idx % SHEET_COLS, idx // SHEET_COLS
        box = (col * SPRITE, row * SPRITE, (col + 1) * SPRITE, (row + 1) * SPRITE)
        sheets[s].crop(box).save(dest)
        written += 1
    for s in sheets:
        (ROOT / "assets" / "achievements" / f"_sheet_{s}.png").unlink(missing_ok=True)
    print(f"icons: {written} sliced, {len(ks) - written} already present")


def fetch_metadata(ua):
    """Probe /achievements/{k} for k in 1..K_MAX, skipping IDs that don't exist."""
    out = []
    for k in range(1, K_MAX + 1):
        try:
            result = json.loads(_get(f"{API_URL}/{k}", ua))
        except urllib.error.HTTPError as e:
            print(f"  #{k}: HTTP {e.code}, skipped")
            continue
        if not result.get('success'):
            print(f"  #{k}: {(result.get('error') or {}).get('msg', 'unknown error')}, skipped")
            continue
        a = result['data']['achievement']
        out.append({f: a[f] for f in META_FIELDS if f in a})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--user-agent', help="overrides config.json's headers.User-Agent")
    ap.add_argument('--force', action='store_true', help="re-download files that already exist")
    args = ap.parse_args()

    ua = _user_agent(args.user_agent)

    print("Fetching achievement metadata...")
    meta = fetch_metadata(ua)
    dest = ROOT / "achievements.json"
    with open(dest, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=1)
        f.write('\n')
    print(f"{dest.name}: {len(meta)} achievements")

    fetch_images(ua, args.force)
    slice_icons([a['k'] for a in meta], ua, args.force)


if __name__ == '__main__':
    main()
