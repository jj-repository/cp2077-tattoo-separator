# Tattoo Switchers for Cyberpunk 2077

Pick your body tattoos in the character editor (the mirror), the same way you pick a hairstyle.
Each body part gets its own setting, and you can change them whenever you like.

This repo contains a small program with a window (the GUI), the build script behind it, and these
instructions. It contains **no tattoo pictures and no game files**. You bring the tattoos: your
own pictures, or tattoos from mods you have downloaded.

---

## Easy way: the GUI

You don't need to know any programming for this, and you don't need Python. You need the things
from [section 4](#4-what-you-need): WolvenKit, ArchiveXL and the Fun Tattoos download.
Sections 1 to 3 explain what the mod does, if you're curious.

The window has a **Help** button (bottom right) that shows these same steps in short, so you
don't need to keep this page open.

1. **Start it.** Download `TattooSwitcher.zip` from the
   [Releases page](https://github.com/jj-repository/cp2077-tattoo-switchers/releases), unzip it
   anywhere (for example on your Desktop), and double-click `TattooSwitcher.exe`.
   If Windows says *"Windows protected your PC"*, click *More info*, then *Run anyway*. It shows
   that for any small program that isn't signed by a company.

   *Alternative with Python:* if you have Python and Pillow (see section 4), you can download this
   repo instead and double-click `Start GUI.bat`. It's the same program.
2. **Find WolvenKit (once).** Click *Find WolvenKit...* and pick `WolvenKit.CLI.exe`. That's the
   console version of WolvenKit (download "WolvenKit Console" from the WolvenKit GitHub page if you
   only have the normal one). The GUI remembers it.
3. **Get the templates (once).** Click *Get templates...* and pick `fun_tattoos_angel_funsix.archive`
   from the [Fun Tattoos](https://www.nexusmods.com/cyberpunk2077/mods/33230) download
   (the "Fun Tattoos Angel Body" file). The GUI takes out the parts it needs by itself.
4. **Name your mod.** Type a short name in *Mod name*, for example `mytat` (lowercase letters,
   digits and `_`). Set *Ink strength*: `1.0` is full colour, `0.6` looks faded.
5. **Add tattoos.** Every tattoo becomes one choice in the character editor.
   - *Add picture (PNG)...*: your own picture. Then type the name shown in the game and pick the
     body part.
   - *Add from tattoo mod...*: pick a tattoo mod's `.archive` (or an `.xbm` from it). The GUI finds
     the tattoo pictures inside: left arm, right arm, and full body.
   - *Split full-body picture...*: for a picture that covers the whole body. The GUI cuts it into
     **Torso**, **Legs** and **Chest** (the whole picture) and shows you the three parts. The red line
     is where it cuts. Leave it at `0.59` unless a design gets cut in the wrong place.
   - *Rename...* changes the name shown in the game. *Remove* takes a tattoo off the list.
6. **Build.** Click *Build mod*. After a minute or two you get two files in the `output` folder
   (*Open folder* shows it):
   - `<mod name>_tattoos.archive`
   - `<mod name>_tattoos.archive.xl`

   **How big is the mod?** That depends only on your tattoos. Each tattoo you added as a PNG
   picture (also each Torso / Legs / Chest piece of a split picture) adds about 5 MB to the
   `.archive` (a bit less for simple designs, more for big detailed ones). Ten tattoos make a mod
   of roughly 50 MB.

   The first time, the GUI may ask for your `Cyberpunk 2077` folder. WolvenKit needs one file from
   the game (`oo2ext_7_win64.dll`) to pack pictures correctly. The GUI copies it into your user
   folder. Nothing in the game is changed.
7. **Install.** Click *Install to game...* and pick your `Cyberpunk 2077` folder, or copy both
   files into `Cyberpunk 2077\archive\pc\mod\` yourself. **Then remove the tattoo mods you took the
   designs from** (see step 6 of the manual way for why).

> **Important: you can add tattoos later, but you can't remove or move tattoos you already built.**
> The game saves your choice as a number ("3rd entry"). If an entry disappeared, old saves would
> suddenly show a different tattoo. The list marks those tattoos with *in built mod*. You can still
> rename them. New tattoos always go to the end of the list.

If something goes wrong, the GUI tells you what's missing, and the box at the bottom shows what it
did. Your list is kept in `work\<mod name>\` (next to `TattooSwitcher.exe`) and comes back when
you start the GUI again. If you unzipped it into a folder Windows doesn't let it write to (like
`Program Files`), the `work` and `output` folders go to `%LOCALAPPDATA%\TattooSwitcher\` instead.

---

## 1. What problem does this solve?

Almost every body-tattoo mod works the same way: it **replaces the skin picture** of your
character. The game has one picture for the arm skin and one for the body skin. A tattoo mod swaps
that picture for one with the tattoo painted in.

That has three downsides:

- The tattoo is **always on**. You can't remove it in game, and it shows in every save.
- You can only use **one** arm tattoo mod and **one** body tattoo mod. Two mods would replace the
  same picture, and only one of them wins.
- There is **nothing to choose** in the character editor.

## 2. What do you get instead?

New settings in the character editor:

| Setting | Choices |
| --- | --- |
| Left Arm Tattoo | Off, Design A, Design B, ... |
| Right Arm Tattoo | Off, Design A, ... |
| Torso Tattoo | Off, ... |
| Legs Tattoo | Off, ... |
| Chest Tattoo | Off, ... |

- **Off** means no tattoo on that body part.
- The settings are independent. For example: a dragon on the left arm, nothing on the right arm,
  and a different design on the torso.
- The tattoos can come from **any tattoo mod** (if its author allows reuse) or from your own
  pictures.

## 3. How does it work?

### The idea: a thin layer on top of the skin

Instead of changing the skin picture, we put a **second, very thin layer** over the skin, like a
temporary tattoo sticker. The layer has exactly the shape of the arm (or the body), so it sits
perfectly on the skin. It is invisible except where the tattoo is printed.

Every tattoo design is just a different picture printed on that same layer. Choosing a design in
the editor tells the game which picture to show on the layer. Choosing *Off* removes the layer.

The skin itself is never touched, so it doesn't matter which skin or other mods you use.

### Why you need the mod "Fun Tattoos" (the "templates")

Making such a layer from scratch is a lot of work: it has to be cut from the body model, fit the
body exactly, follow the breast-size slider, and be registered in the character editor. The mod
[Fun Tattoos](https://www.nexusmods.com/cyberpunk2077/mods/33230) by funsix has already done all of
that for the female **Angel** body. It contains ready-made layers for the left arm, the right arm
and the whole body, plus one ready-made editor entry.

These finished pieces are what this README calls **templates**. Our script doesn't create layers
itself. It **copies the templates** once for every design you want, prints your design on each
copy, and writes all the editor settings.

**You don't use Fun Tattoos for its own tattoos, only for these parts.** We can't include the
templates in this repo, because they are funsix's work. Everyone downloads Fun Tattoos and takes
them from there.

### Where do Torso, Legs and Chest come from?

Fun Tattoos has separate layers for each arm, but only **one layer for the whole body**. And most
full-body tattoo mods come as one picture that covers torso and legs together.

So that you can still choose Torso and Legs separately, our tool `tools/split_overlay.py` cuts
such a picture into three pictures:

- `torso`: only the upper body
- `legs`: only the legs
- `chest`: the full picture, uncut

Each picture becomes a choice in its own setting. All three use the same body layer, but they
still don't replace each other (details in section 6).

## 4. What you need

- Cyberpunk 2077 with [ArchiveXL](https://www.nexusmods.com/cyberpunk2077/mods/4198). ArchiveXL is
  what lets mods add new settings to the character editor.
- [WolvenKit](https://github.com/WolvenKit/WolvenKit), the standard modding tool for packing
  game files.
- Only for `Start GUI.bat` or the manual way (not for `TattooSwitcher.exe`): Python 3.8 or newer
  ([python.org](https://www.python.org/), tick *Add python.exe to PATH* when installing). For the
  GUI and `tools/split_overlay.py` you also need Pillow: open a command prompt and type
  `pip install pillow`.
- [Fun Tattoos](https://www.nexusmods.com/cyberpunk2077/mods/33230), for the templates (see
  section 3).
- A **female V with the Angel body**. The templates are made for that body. On another body the
  layers would not fit.

## 5. Manual way (step by step)

This is what the GUI does for you. Use it if you want full control, or to script your own build.

### Step 1: Get the templates out of Fun Tattoos

Download Fun Tattoos and open its Angel-body `.archive` in WolvenKit. Add these 8 files to a
WolvenKit project and convert each one to JSON (right-click → *Convert to JSON*, or on the command
line `WolvenKit.CLI convert serialize <file>`):

```
funsix\ccxl\arm_tattoo\appearances\arm_tattoo.app
funsix\ccxl\arm_tattoo\materialinstance\arm_tattoo.mi
funsix\ccxl\arm_tattoo\inkcc\arm_tattoo_pwa.inkcharcustomization
funsix\ccxl\arm_tattoo\meshes\arm_tattoo\fun_arm_tattoo_left_pwa.mesh
funsix\ccxl\arm_tattoo\meshes\arm_tattoo\fun_arm_tattoo_right_pwa.mesh
funsix\ccxl\chest_tattoo\appearances\chest_tattoo.app
funsix\ccxl\chest_tattoo\meshes\chest_tattoo\your_chest_tattoo.mesh
funsix\ccxl\chest_tattoo\meshes\chest_tattoo\your_chest_tattoo.morphtarget
```

Put all 8 `.json` files into one folder, for example `templates/`.

### Step 2: Prepare your tattoo pictures

The game needs pictures in its own `.xbm` format.

- **From an arm tattoo mod:** it contains `femme_arm_left_01_overlay.xbm` and/or
  `femme_arm_right_01_overlay.xbm`. That's your tattoo. Copy it and give it a new name.
- **From a full-body tattoo mod:** it contains `v_overlay.xbm`. Export it to PNG in WolvenKit, cut
  it up with
  ```
  python tools/split_overlay.py v_overlay.png split mydesign
  ```
  and turn the three PNGs back into `.xbm` (see the next point).
- **Your own PNG:** copy any existing tattoo `.xbm` to the new name, then import your PNG over it
  in WolvenKit (import with *keep* settings, on the command line `import -k`). That way the
  picture keeps the right game settings.

### Step 3: Write your list (`options.json`)

Copy `options.example.json` to `options.json`. This file is your **list of tattoos**:

- `prefix`: a short name for your mod, for example `mytat`. It goes into every file name so that
  nothing clashes with other mods.
- `depot_root`: the folder your files go into inside the mod, for example `mytat/tattoos`.
- `diffuse_alpha`: ink strength. `1.0` is full colour, `0.6` looks faded (that's what Fun
  Tattoos uses).
- `parts`: the settings in the editor (Left Arm, Torso, ...). `kind` says which layer the part
  uses: `arm_left`, `arm_right` or `body`. `ui_index` sets where the setting appears in the
  editor.
- `options`: one line per tattoo, with a name (`id`), its setting (`part`), the name shown in
  the editor (`label`) and the path to its picture (`texture`, from step 2).

> **Important: only ever add new tattoos at the end of a part.** The game saves your choice as a
> number ("3rd entry"). If you move or delete entries, old saves suddenly show a different tattoo.
> The script remembers the order in `options.lock.json` and refuses to build if it changes.

### Step 4: Run the script

```
python build.py templates out
```

The script writes all the mod files as JSON into the `out` folder, and lists which pictures it
expects where. It also checks itself: every choice exists, every choice has its picture, and no
name appears twice.

### Step 5: Pack it into a mod

1. In a WolvenKit project, convert each JSON file from `out` back into a game file
   (*Convert from JSON*, or `WolvenKit.CLI convert deserialize <file>.json`), at the same path
   inside the project's `source\archive` folder.
2. Put your `.xbm` pictures from step 2 at the paths from your list.
3. Pack the project (`WolvenKit.CLI pack`) into `<prefix>_tattoos.archive`.

### Step 6: Install it

Put both files into `Cyberpunk 2077\archive\pc\mod\`:

- `<prefix>_tattoos.archive`
- `<prefix>_tattoos.archive.xl` (written by the script into `out`)

**Then remove the old tattoo mods you took the designs from.** Otherwise they keep painting their
tattoo onto the skin, even when the setting is *Off*.

## 6. Technical details for modders

### What each file does

| File | What it does |
| --- | --- |
| `.mi` (material) | Says how the layer is drawn: as a decal (a picture laid over the skin), with ink strength `DiffuseAlpha`. |
| `.mesh` | The layer itself (the shape of the arm or body). One mesh per layer, with one look per design. |
| `.morphtarget` | Body only: lets the body layer follow the breast-size slider. |
| `.app` | One entry per design that says "show this layer with this design". |
| `.inkcharcustomization` | The settings in the editor: per part one setting with *Off* plus the designs. |
| `.archive.xl` | Tells ArchiveXL to load these editor settings. |

### Why the settings don't replace each other

Every design of one part has the same internal name, for example `mytat_left_arm_tattoo`. If you
choose a new design for that part, it replaces the old one, so each part only ever shows one
design. Different parts have different names, so they add up. That's how Torso, Legs and Chest can
be worn together, even though all three use the same body layer.

### Problems we ran into (the script handles them)

- **Duplicate internal numbers.** The JSON files number their internal parts. Copied parts keep
  their numbers, and above roughly 23 designs they collided and designs broke. The script
  renumbers everything after copying (HandleId / HandleRefId, and `BufferId` in the `.app`).
- **Fixed IDs.** The layer IDs (CRUIDs) are derived from your `prefix` and the part. They stay the
  same on every rebuild and never clash with Fun Tattoos' own IDs.
- **Order of the choices.** See the note in step 3.
- **Breast slider.** The body layer needs its own copy of the morphtarget, pointed at our layer.
  Without it the tattoo floats off the body when the breasts are larger.
- **Every part of the mesh needs the material.** Otherwise patches of the arm stay bare.
- **Colour only.** The layer only shows colour. If a tattoo mod also ships a normal map
  (relief, scars), it isn't used here.
- **Too harsh?** If the tattoo looks too strong, lower `diffuse_alpha`.

### The torso/legs split

On the Angel body, torso and legs share one picture. The torso is on the left side of the
picture (horizontal position 0.22 to 0.58) and the legs on the right side (0.61 to 0.95).
`split_overlay.py` cuts at 0.59 and scales to 4096 px (game pictures are often 8192 px; you can't
see the difference on the layer, and the mod gets much smaller). This value is **measured on the
Angel body**. Another body needs its own value (`--split`).

### Adding more body parts

- **Another setting on an existing layer** (for example a second torso setting, "Back"): add a
  part with `kind: body`. It gets its own name and adds to the others.
- **A new layer** (hands, lower legs, ...): Fun Tattoos has more templates
  (`fun_hands_tattoo_*_pwa.mesh`, `fun_llegs_tattoo_*_pwa.mesh`, ... with their `.app`). Convert
  the mesh and its `.app` to JSON and add an entry to `KINDS` at the top of `build.py`.

## 7. Using it with a salon or tattoo-studio mod

Every setting has a fixed internal name built from your prefix and the part, for example
`mytat_left_arm_tattoo_switcher`. Mods that decide which editor settings appear where (for example
NC Salons and its per-service filter) can use these names to show the tattoo settings only at a
tattoo studio and hide them from the mirror at home. Where to enter the names depends on that mod.

## Credits

- **funsix**, [Fun Tattoos](https://www.nexusmods.com/cyberpunk2077/mods/33230): the method of
  putting tattoos on a layer, and the templates this script builds on.
- **psiberx**, [ArchiveXL](https://www.nexusmods.com/cyberpunk2077/mods/4198), including the
  character editor support.
- The [WolvenKit](https://github.com/WolvenKit/WolvenKit) team.

**The tattoo designs belong to their authors.** This repo contains no pictures. Only use designs
from mods whose authors allow reuse (and credit them), or your own. Don't upload a mod with other
people's designs unless they allow it.

## License

To build `TattooSwitcher.exe` yourself, run `build_exe.bat` (needs Python; the result is in
`dist\TattooSwitcher\`). `tattoo_switcher_gui.py --guitest ...` (or `TattooSwitcher.exe --guitest ...`)
clicks through every button of the real window and writes `guitest.log`; the arguments are listed
at the top of `guitest.py`.

The code in this repo (`build.py`, `tattoo_switcher_gui.py`, `guitest.py`, `tools/`) is under the MIT license, see [LICENSE](LICENSE). That
does not cover Fun Tattoos' files, game files or tattoo pictures.

by jj-repository
