"""Android can't use the site's .woff2 or chain custom fallbacks, so merge each Latin font with Mukta (Devanagari)
into one TTF per weight, matching the CSS stacks in ledger/tailwind.css. Renamed, as the OFL requires for modified fonts.

Run from the repo root after changing the site's fonts:
    uv run --with fonttools --with brotli python android/tools/make_fonts.py
"""
import os
import shutil
import tempfile
from fontTools.ttLib import TTFont
from fontTools.merge import Merger

SRC = "ledger/static/ledger/fonts/"
OUT = "android/app/src/main/res/font/"
TMP = tempfile.mkdtemp()
os.makedirs(OUT, exist_ok=True)

def ttf(name):
    t = TTFont(SRC + name + ".woff2"); t.flavor = None
    path = f"{TMP}/{name}.ttf"; t.save(path); return path

# (output, family, style, latin font, Mukta weight) — weights as in --font-sans / --font-display
BUILDS = [
    ("paisapeek_sans_regular", "Paisapeek Sans", "Regular", "figtree-latin-400-normal", 400),
    ("paisapeek_sans_medium", "Paisapeek Sans", "Medium", "figtree-latin-500-normal", 400),  # no Mukta 500; CSS picks 400 too
    ("paisapeek_sans_semibold", "Paisapeek Sans", "SemiBold", "figtree-latin-600-normal", 600),
    ("paisapeek_display_semibold", "Paisapeek Display", "SemiBold", "bricolage-grotesque-latin-600-normal", 600),
    ("paisapeek_display_extrabold", "Paisapeek Display", "ExtraBold", "bricolage-grotesque-latin-800-normal", 800),
]
for out, family, style, latin, mukta in BUILDS:
    a, b = ttf(latin), ttf(f"mukta-devanagari-{mukta}-normal")
    merged = Merger().merge([a, b])
    base = TTFont(a)
    for tag, fields in {"hhea": ("ascent", "descent", "lineGap"),
                        "OS/2": ("sTypoAscender", "sTypoDescender", "sTypoLineGap", "usWinAscent", "usWinDescent")}.items():
        for f in fields:  # keep the Latin font's line metrics so English text sits exactly as on the web
            setattr(merged[tag], f, getattr(base[tag], f))
    name = merged["name"]
    for rec in list(name.names):
        if rec.nameID in (1, 3, 4, 6, 16, 17):
            name.removeNames(nameID=rec.nameID)
    full = f"{family} {style}"
    for nid, val in {1: family, 2: style, 3: f"{full}; Paisapeek", 4: full, 6: full.replace(" ", "-"), 16: family, 17: style}.items():
        name.setName(val, nid, 3, 1, 0x409)
    merged.save(OUT + out + ".ttf")
    print(out, os.path.getsize(OUT + out + ".ttf") // 1024, "KB,", len(merged.getGlyphOrder()), "glyphs")
for lic in ("bricolage", "figtree", "mukta"):  # the OFL travels with the fonts inside the APK
    shutil.copy(f"{SRC}OFL-{lic}.txt", f"android/app/src/main/assets/licenses/OFL-{lic}.txt")
