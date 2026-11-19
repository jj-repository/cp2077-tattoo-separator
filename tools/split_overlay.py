"""Split a full-body v_overlay tattoo texture into separate torso / legs / chest PNGs.

Full-body tattoo mods usually replace one texture (base\\v_textures\\body\\v_overlay.xbm) that covers
torso AND legs, because the body mesh keeps both in one UV map. To get separate Torso and Legs
options, mask the texture by UV:  torso = u < SPLIT_U, legs = u >= SPLIT_U.  Chest = unmasked copy
(useful for designs that only cover the chest, or to keep a design whole on its own row).

SPLIT_U = 0.59 is measured on the Angel body (torso mesh t0_000_pwa_base__full: front torso about
u 0.22-0.58, legs about u 0.61-0.95). It is BODY-SPECIFIC: check your body's UV layout first.

The game textures are often 8192 px; the decal looks the same at 4096 and the archive halves.

usage: python split_overlay.py <v_overlay.png> <out dir> <name> [--size 4096] [--split 0.59]
  -> <name>_torso.png, <name>_legs.png, <name>_chest.png
Export the mod's v_overlay.xbm to PNG with WolvenKit first; import the results back as .xbm (see README).
Needs Pillow (pip install pillow).
"""

import argparse, os
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("png")
ap.add_argument("out")
ap.add_argument("name")
ap.add_argument("--size", type=int, default=4096)
ap.add_argument(
    "--split",
    type=float,
    default=0.59,
    help="body-specific UV u where torso ends and legs begin",
)
a = ap.parse_args()

im = Image.open(a.png).convert("RGBA")
if im.size != (a.size, a.size):
    im = im.resize((a.size, a.size), Image.LANCZOS)
cut = round(a.split * a.size)
os.makedirs(a.out, exist_ok=True)

torso = im.copy()
torso.paste((0, 0, 0, 0), (cut, 0, a.size, a.size))  # clear u >= split
legs = im.copy()
legs.paste((0, 0, 0, 0), (0, 0, cut, a.size))  # clear u < split
for part, img in (("torso", torso), ("legs", legs), ("chest", im)):
    p = os.path.join(a.out, "%s_%s.png" % (a.name, part))
    img.save(p)
    print(
        p, "ink bbox:", img.getchannel("A").getbbox()
    )  # None = nothing left on this side
