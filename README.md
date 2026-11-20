# Tattoo Switchers for Cyberpunk 2077

Normally a tattoo mod paints its tattoo onto your character permanently. You can't turn it off,
and you can't combine two tattoo mods.

This script turns tattoos into **choices in the character editor** (the mirror), like hairstyles:

- Each body part gets its own setting: Left Arm, Right Arm, Torso, Legs, Chest.
- For each part you pick a tattoo, or *Off* for no tattoo there.
- The parts are independent. For example: a dragon on the left arm, nothing on the right arm,
  and a different design on the torso.
- You can change them any time at the mirror.

This repo holds a small build script and docs. **It contains no textures and no game files.**

## The problem

Most tattoo mods are *replacers*: they overwrite the body's overlay textures
(`femme_arm_left_01_overlay`, `femme_arm_right_01_overlay`, `v_overlay` for torso and legs).
That means:

- the tattoo is always on, for every save,
- you can have only one arm/body tattoo mod at a time (they fight over the same file),
- there is nothing to pick in character creation.

## The method

Instead of replacing textures, we add **our own decal meshes** as character-creation body options,
using ArchiveXL's character-creation support (CCXL). The approach and the template files come from
[Fun Tattoos](https://www.nexusmods.com/cyberpunk2077/mods/33230) by funsix.

**Decal copies of the body.** A decal mesh is a copy of the arm (or body) mesh that is drawn on top
of the skin. Each tattoo design is one *appearance* of that mesh, with its own material that only
points at the design's texture. Because it's a separate mesh, the skin underneath stays untouched.

**One switcher row per body part.** Each part gets a row: *Off* (no tattoo on that part), then every design for that part.

**How the files fit together:**

| File | What it holds |
| --- | --- |
| `.mi` | One shared decal material (`base\materials\mesh_decal.mt`) with `DiffuseAlpha`. |
| `.mesh` | One per template kind (left arm, right arm, body). One appearance + one local material per design; every render chunk of the mesh uses that material. |
| `.morphtarget` | Body only: a copy of the template morphtarget, re-pointed at our body mesh. |
| `.app` | One appearance `w__<option id>` per design, with one component that shows the mesh in that design's appearance. |
| `.inkcharcustomization` | Per part: a switcher row, an *Off* option and one body option per design (each option loads its `.app` appearance). |
| `.archive.xl` | Registers the `.inkcharcustomization` with ArchiveXL. |

**How the parts stack.** In the `.app`, every design of one part uses the *same component name*
(for example `mytat_left_arm_tattoo`). Picking a new design for that part replaces the component,
so a part only ever shows one design. Different parts use different component names, so they add
up, even when they share a mesh: Torso, Legs and Chest are all drawn by the same body decal mesh,
just as three separate components.

**Why decals.** `mesh_decal.mt` blends a diffuse texture on top of the skin. Tattoos are only colour,
so we keep just `DiffuseTexture` and drop normal/detail maps. That also means any normal map a
tattoo mod ships (scar relief, skin detail) is not used.

**Breast morph.** The body decal uses a morph-target component. Its morphtarget is a copy of the
template's, re-pointed at our body mesh, so chest and torso tattoos follow the character creator's
breast-size slider instead of floating off the body.

## What you need

- Cyberpunk 2077 with [ArchiveXL](https://www.nexusmods.com/cyberpunk2077/mods/4198) (and its requirements)
- [WolvenKit](https://github.com/WolvenKit/WolvenKit) (GUI or CLI)
- Python 3.8+ (no extra packages; `tools/split_overlay.py` needs Pillow)
- [Fun Tattoos](https://www.nexusmods.com/cyberpunk2077/mods/33230) by funsix, for the template files
- A female V with the Angel body. The templates are `pwa` (female) files made for that body.

### Getting the templates

Download Fun Tattoos and open its Angel-body `.archive` in WolvenKit. Add these 8 files to a
project and serialize each one to JSON (`WolvenKit.CLI convert serialize <file>`, or right-click
→ *Convert to JSON* in the GUI):

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

Put all the resulting `<name>.json` files into one flat folder, e.g. `templates/`.
These are funsix's files: use them to build your own mod, don't redistribute them as-is.

## Build steps

1. **Write your config.** Copy `options.example.json` to `options.json` and edit it.
   - `prefix`: a short unique name; used for file names, component names and row names.
   - `depot_root`: where your files live inside the archive (e.g. `mytat/tattoos`).
   - `diffuse_alpha`: ink strength. 1.0 = full; Fun Tattoos uses 0.6 for a faded look.
   - `parts`: the rows. `kind` is the mesh it draws on (`arm_left`, `arm_right` or `body`);
     `ui_index` places the row in the character creator.
   - `options`: one entry per design: `id` (unique, start it with your prefix), `part`, `label`
     (shown in the menu) and `texture` (the `.xbm` depot path you will add in step 4).

   **Only ever add options at the end of a part.** Saves remember the row's index; reordering or
   removing options makes old saves show a different tattoo. `build.py` writes `options.lock.json`
   and refuses to build if the order of existing options changes.

2. **Run the script.**
   ```
   python build.py templates out
   ```
   It writes `out/<depot path>.json` for every file, plus `out/<prefix>_tattoos.archive.xl`,
   and prints the texture paths it expects. It also self-checks the result (every row option
   exists, every option has its app appearance, no duplicate names).

3. **Deserialize.** Turn each JSON back into a game file inside a WolvenKit project's `source\archive`
   folder at the same depot path (`WolvenKit.CLI convert deserialize <file>.json`, or *Convert from
   JSON* in the GUI).

4. **Add the textures** as `.xbm` at the paths from your config.
   - *Arm designs* from an arm-tattoo mod: its `femme_arm_left_01_overlay.xbm` /
     `femme_arm_right_01_overlay.xbm` can simply be copied and renamed.
   - *Your own PNGs*: copy any existing overlay `.xbm` to the target path, then import your PNG
     onto it (WolvenKit import with *keep* settings, CLI `import -k`). That keeps the right
     texture settings.
   - *Full-body overlays* (`v_overlay`): split them into torso / legs / chest first, see below.

5. **Pack** the project (`WolvenKit.CLI pack`) into `<prefix>_tattoos.archive`.

6. **Install**: put the `.archive` and the generated `<prefix>_tattoos.archive.xl` side by side in
   `archive\pc\mod\`. The `.xl` contains just:
   ```yaml
   customizations:
     female: mytat\tattoos\mytat_tattoos_pwa.inkcharcustomization
   ```

Then remove the original tattoo replacer mods, or they keep painting the tattoo on the skin.

### Splitting a full-body overlay

Full-body tattoo mods replace `base\v_textures\body\v_overlay.xbm`. On the Angel body, the torso
mesh carries torso *and* legs in one UV map, so one texture covers both. To make separate Torso and
Legs options, export the texture to PNG and run:

```
python tools/split_overlay.py v_overlay.png split mydesign
```

This writes `mydesign_torso.png` (u < 0.59), `mydesign_legs.png` (u >= 0.59) and
`mydesign_chest.png` (unmasked), scaled to 4096 px (game files are often 8192; the decal looks the
same and the archive is much smaller). **The 0.59 split is measured on the Angel body**
(front torso is roughly u 0.22-0.58, legs u 0.61-0.95). Another body needs its own value
(`--split`); check the UV layout first.

### Adding more parts

- **Another row on an existing mesh** (e.g. a second torso layer, "Back"): add a part with the
  same `kind` (`body`). It gets its own component, so it stacks with the others.
- **A new mesh** (hands, lower legs, ...): Fun Tattoos ships more templates
  (`fun_hands_tattoo_*_pwa.mesh`, `fun_llegs_tattoo_*_pwa.mesh`, ... with their `.app`). Serialize the
  mesh and its `.app`, then add an entry to `KINDS` at the top of `build.py` (mesh file, app file,
  which appearance in that app to copy, and the template mesh path to replace).

## Gotchas

Each of these broke something in-game before it was fixed; `build.py` handles them for you.

- **HandleId / HandleRefId.** WolvenKit JSON uses handle ids that must be unique per file. Copying
  appearances copies their ids; past roughly 23 options they collided and options broke. The
  script renumbers all handles after copying.
- **BufferId.** Each `.app` appearance has a `compiledData` buffer whose `BufferId` must also be
  unique across the whole file.
- **Stable component ids (CRUIDs).** Component ids are derived from `prefix` + part, so they are
  the same on every rebuild and never equal Fun Tattoos' ids.
- **Append-only option order.** See step 1.
- **One component per part.** Same component name = options replace each other; different names
  = parts stack. Don't give two parts the same id.
- **Morphtarget.** The body decal needs its own morphtarget copy re-pointed at your mesh, or it
  ignores the breast slider.
- **Decal material.** Diffuse only, strength via `DiffuseAlpha`. If ink looks too hard, lower
  `diffuse_alpha`.
- **Every render chunk gets the material.** Otherwise parts of the limb stay bare.
- **Old replacers.** Leave the original tattoo replacer installed and the tattoo stays on the skin even when the row is set to Off.

## Using it with a salon or tattoo-studio mod

The switcher rows are normal character-creation body options with their own `uiSlot` names, built
from your prefix and part, e.g. `mytat_left_arm_tattoo_switcher`. Mods that filter which
character-creation rows are shown by `uiSlot` (for example NC Salons' service filter) can list these
names to show your tattoo rows only at a tattoo studio, and hide them from the mirror. Look up the
salon mod's config for where to add the slot names.

## Credits

- **funsix**, [Fun Tattoos](https://www.nexusmods.com/cyberpunk2077/mods/33230): the CCXL tattoo
  method and the template files this script builds on.
- **psiberx**, [ArchiveXL](https://www.nexusmods.com/cyberpunk2077/mods/4198) (incl. character
  creation support).
- The [WolvenKit](https://github.com/WolvenKit/WolvenKit) team.

**Tattoo designs belong to their authors.** This repo includes no textures. Only use textures from
mods whose permissions allow reuse (and credit them), or use your own artwork. Don't upload a
build containing other people's designs unless they allow it.

## License

The code in this repo (`build.py`, `tools/`) is MIT licensed, see [LICENSE](LICENSE).
This does not cover Fun Tattoos' files, game files or any tattoo textures.

by jj-repository
