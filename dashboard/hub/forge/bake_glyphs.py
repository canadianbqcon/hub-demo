"""Bake the stat rail's glyph set into the data URIs `forge.html` inlines.

    python3 bake_glyphs.py            # prints the GLYPH block, ready to paste
    python3 bake_glyphs.py --check    # self-check on the shipped block

Riot ships these as 20x20 PNGs and nothing larger exists: the two atlases hold
the same art at the same scale (~20px content on a 27px pitch), and there is no
2x variant anywhere in the exported index. So resolution is not the lever. What
IS the lever is how many times the art gets resampled on its way to the screen.

The set this replaced was nearest-neighbour doubled to 40x40, which the browser
then downsampled to a 22px box -- a 40:22 ratio, so every source pixel landed
across an uneven fraction of a screen pixel and the whole rail read soft. These
are baked at 44x44 instead, exactly 2x the largest box the glyph is drawn in, so
a 1x screen halves it cleanly and a 2x screen draws it 1:1.

Uniformity is the other half. Riot's tiles are not consistently inset: most
glyphs sit in 18x18 of their 20x20 tile, but `onhit`, `scalems` and
`scaletenacity` run edge to edge, which made three rows read ~11% larger than
the rest and touch their box. Each glyph is cropped to its own alpha bounds,
scaled so its LONG side is CONTENT px, and centred -- so every row carries the
same visual weight with the same margin, and none of them is clipped.
"""
import base64
import io
import re
import sys
import urllib.request
from pathlib import Path

from PIL import Image

CDN = ('https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/'
       'global/default/assets/ux/fonts/texticons/lol')
CANVAS = 44      # 2x the 22px rail box; the inspector (20px) and hover card (18px) fit under it
CONTENT = 40     # long side of the art itself, leaving a 2px margin at 2x

# Row label -> Riot's own file name. The name is what settles which glyph is
# which: `scalels` (Life Steal) is the crossed drop and `scalesv` (the Omnivamp
# row's tag) is the fangs, and reading that off an unlabelled atlas is how they
# got swapped once. Gold is the one row answered from `gameplay/`, not
# `statsicon/`. Capstone is hand-drawn -- see CROWN below.
SOURCE = {
    'Attack Damage': 'statsicon/scalead',
    'Critical Strike': 'statsicon/scalecrit',
    'Attack Speed': 'statsicon/scaleas',
    'On-Hit Effects': 'statsicon/onhit',
    'Armor Penetration': 'statsicon/scaleapen',
    'Life Steal': 'statsicon/scalels',
    'Omnivamp': 'statsicon/scalesv',
    'Ability Power': 'statsicon/scaleap',
    'Magic Penetration': 'statsicon/scalempen',
    'Mana': 'statsicon/scalemana',
    'Mana Regen': 'statsicon/scalemanaregen',
    'Ability Haste': 'statsicon/scaleah',
    'Health': 'statsicon/scalehealth',
    'Health Regen': 'statsicon/scalehpregen',
    'Armor': 'statsicon/scalearmor',
    'Magic Resist': 'statsicon/scalemr',
    'Tenacity': 'statsicon/scaletenacity',
    'Movement': 'statsicon/scalems',
    'Heal & Shield Power': 'statsicon/scalehealshield',
    'Gold Per 10 Seconds': 'gameplay/goldcoins',
}
CROWN = 'Scales off your stats'
HTML = Path(__file__).parent / 'frontend' / 'forge.html'


def normalise(im):
    """Crop to the art, scale the long side to CONTENT, centre it on CANVAS.

    The short side rounds to an even number so the centring is exact rather than
    half a pixel off; that costs under 1.5% of aspect and nothing visible.
    """
    im = im.convert('RGBA')
    box = im.split()[3].getbbox()
    art = im.crop(box)
    w, h = art.size
    if w >= h:
        tw, th = CONTENT, max(2, round(h * CONTENT / w / 2) * 2)
    else:
        th, tw = CONTENT, max(2, round(w * CONTENT / h / 2) * 2)
    art = art.resize((tw, th), Image.Resampling.LANCZOS)
    out = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
    out.paste(art, ((CANVAS - tw) // 2, (CANVAS - th) // 2))
    return out


def as_data_uri(im):
    buf = io.BytesIO()
    im.save(buf, 'WEBP', lossless=True, quality=100, method=6)
    return 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode()


def shipped():
    """The GLYPH block currently in forge.html, as {label: PIL image}."""
    src = HTML.read_text()
    blk = src[src.index('const GLYPH = {'):]
    blk = blk[:blk.index('\n};')]
    return {k: Image.open(io.BytesIO(base64.b64decode(b64))).convert('RGBA')
            for k, b64 in re.findall(
                r'"([^"]+)":\s*"data:image/[a-z]+;base64,([^"]+)"', blk)}


def bake():
    out = {}
    for label, path in SOURCE.items():
        # CommunityDragon 403s the stdlib's default agent string.
        req = urllib.request.Request(f'{CDN}/{path}.png',
                                     headers={'User-Agent': 'vault-forge/1.0'})
        raw = urllib.request.urlopen(req, timeout=30).read()
        out[label] = normalise(Image.open(io.BytesIO(raw)))
    # The crown is the one glyph Riot does not ship in this idiom, so it is
    # re-normalised from the copy already in the page rather than refetched.
    out[CROWN] = normalise(shipped()[CROWN])
    return out


def check():
    """Every shipped glyph is CANVAS square, uncropped, uniform and centred."""
    bad = []
    for label, im in shipped().items():
        w, h = im.size
        box = im.split()[3].getbbox()
        if box is None:
            bad.append(f'{label}: fully transparent, no art to measure')
            continue
        cw, ch = box[2] - box[0], box[3] - box[1]
        if (w, h) != (CANVAS, CANVAS):
            bad.append(f'{label}: {w}x{h}, not {CANVAS} square')
        if box[0] == 0 or box[1] == 0 or box[2] == w or box[3] == h:
            bad.append(f'{label}: art touches the edge at {box}')
        if max(cw, ch) != CONTENT:
            bad.append(f'{label}: long side {max(cw, ch)}, not {CONTENT}')
        if box[0] != w - box[2] or box[1] != h - box[3]:
            bad.append(f'{label}: off centre, margins {box[0]}/{w - box[2]} '
                       f'{box[1]}/{h - box[3]}')
    print('\n'.join(bad) if bad else
          f'all {len(shipped())} glyphs {CANVAS}px, uncropped, {CONTENT}px long side, centred')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--check' in sys.argv:
        sys.exit(check())
    print('const GLYPH = {')
    for label, im in bake().items():
        print(f'  "{label}": "{as_data_uri(im)}",')
    print('};')
