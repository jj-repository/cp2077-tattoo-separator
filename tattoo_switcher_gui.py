"""Tattoo Switchers GUI: build a tattoo-switcher mod without touching JSON or the command line.

Start it with "Start GUI.bat" (or: python tattoo_switcher_gui.py). Everything the README's
"Manual way" does by hand runs here through the WolvenKit CLI and build.py.

Windows .exe (build_exe.bat, PyInstaller): the same file frozen. Settings and the work and output
folders then live next to TattooSwitcher.exe, or in %LOCALAPPDATA%/TattooSwitcher if that folder is
read-only.

Self-test without a window (needs the Fun Tattoos archive and some tattoo sources):
  python tattoo_switcher_gui.py --selftest <empty scratch dir> --fun <Fun Tattoos Angel .archive>
      --arm <arm tattoo mod .archive or .xbm> --png <arm tattoo .png> --body <full-body mod .archive / v_overlay .xbm / .png>
      [--wk <WolvenKit.CLI.exe>]
  (TattooSwitcher.exe --selftest ... works too; the windowed exe has no console, so it writes
  selftest.log into the scratch dir and exits 0 / 1.)
"""

import contextlib, io, json, os, queue, re, shutil, subprocess, sys, tempfile, threading, traceback

VERSION = "1.1"
HERE = os.path.dirname(
    os.path.abspath(__file__)
)  # bundled files (frozen: PyInstaller's _internal)
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import build as tsbuild  # noqa: E402  (build.py next to this file)


def _user_dir():
    """Where settings, work and output go: this folder, or next to the .exe when frozen."""
    if not getattr(sys, "frozen", False):
        return HERE
    for d in (
        os.path.dirname(sys.executable),
        os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "TattooSwitcher"
        ),
    ):
        # really try to write: os.access lies on Windows, and tempfile retries forever on a denied folder
        test = os.path.join(d, ".write_test")
        try:
            os.makedirs(d, exist_ok=True)
            open(test, "w").close()
            os.remove(test)
            return d
        except OSError:
            pass
    raise SystemExit("No writable folder for Tattoo Switchers' settings.")


USER = _user_dir()

try:
    from PIL import Image
    from split_overlay import split as split_image
except ImportError:  # shown as a message box / console line in main()
    Image = None

SETTINGS = os.path.join(USER, "gui_settings.json")
OODLE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "oo2ext_7_win64.dll")

# The 8 Fun Tattoos files build.py copies, plus one texture per layer used as the base when a PNG
# is turned into an .xbm (import -k keeps the texture's game settings, takes the PNG's pixels).
TEMPLATES = sorted(
    {
        f
        for k in tsbuild.KINDS.values()
        for f in (k["mesh"], k["app"], k.get("morph"))
        if f
    }
    | {tsbuild.MI_TEMPLATE, tsbuild.CC_TEMPLATE}
)
BASE_XBM = {
    "arm_left": "pwa_tattoo_arm.xbm",
    "arm_right": "pwa_tattoo_arm.xbm",
    "body": "pwa_tattoo_chest.xbm",
}
FUN_REGEX = r"ccxl.(arm|chest)_tattoo.(appearances|materialinstance|inkcc|meshes).|pwa_tattoo_(arm|chest)[.]xbm$"

with open(os.path.join(HERE, "options.example.json"), encoding="utf-8") as _f:
    PARTS = json.load(_f)["parts"]  # same rows/kinds/ui_index as the manual way
PART_NAME = {p["id"]: p["label"].replace(" Tattoo", "") for p in PARTS}
PART_KIND = {p["id"]: p["kind"] for p in PARTS}
SPLIT_PARTS = ("torso", "legs", "chest")
# textures that tattoo mods replace, and the row they belong to ("full" = full-body, split it)
MOD_TEXTURES = {
    "femme_arm_left_01_overlay.xbm": "left_arm",
    "femme_arm_right_01_overlay.xbm": "right_arm",
    "v_overlay.xbm": "full",
}


class UserError(Exception):
    """A problem the user can fix; the message is shown as is."""


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s):
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "tattoo"


# ----------------------------------------------------------------------------- WolvenKit CLI
class WolvenKit:
    def __init__(self, exe, log=print):
        if not exe or not os.path.isfile(exe):
            raise UserError(
                "WolvenKit is not set up yet.\nClick 'Find WolvenKit...' and pick WolvenKit.CLI.exe "
                "(it comes with WolvenKit, or download the 'WolvenKit Console' zip from GitHub)."
            )
        if os.path.basename(exe).lower() != "wolvenkit.cli.exe":
            raise UserError(
                "Please pick WolvenKit.CLI.exe (the console version), not %s."
                % os.path.basename(exe)
            )
        self.exe, self.log = exe, log

    def run(self, *args, ok=(0,)):
        args = [str(a) for a in args]
        self.log(
            "  WolvenKit %s %s"
            % (args[0], os.path.basename(args[1]) if len(args) > 1 else "")
        )
        try:
            r = subprocess.run(
                [self.exe, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,  # the windowed .exe has no stdin handle to inherit
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as e:
            raise UserError("Could not start WolvenKit (%s)." % e)
        out = r.stdout + r.stderr
        if (
            r.returncode not in ok
            or "Unhandled exception" in out
            or "Error       ]" in out
        ):
            tail = "\n".join(out.strip().splitlines()[-8:])
            raise UserError(
                "WolvenKit could not do '%s'. Its last messages:\n%s" % (args[0], tail)
            )
        return out

    def unbundle(self, archive, out, regex):
        os.makedirs(out, exist_ok=True)
        self.run("unbundle", archive, "-o", out, "-r", regex)

    def to_png(self, xbm, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        self.run("export", xbm, "-o", out_dir, "--uext", "png")
        png = os.path.join(out_dir, os.path.splitext(os.path.basename(xbm))[0] + ".png")
        if not os.path.isfile(png):
            raise UserError(
                "WolvenKit did not turn %s into a picture." % os.path.basename(xbm)
            )
        return png

    def listing(self, archive):
        out = self.run("archiveinfo", archive, "-l")
        return [
            l.strip()
            for l in out.splitlines()
            if "\\" in l and not l.lstrip().startswith("[")
        ]


def oodle_ok():
    return os.path.isfile(OODLE)


def install_oodle(game):
    """WolvenKit only compresses textures correctly with the game's Oodle DLL in %LOCALAPPDATA%."""
    src = os.path.join(game, "bin", "x64", "oo2ext_7_win64.dll")
    if not os.path.isfile(src):
        raise UserError(
            "That doesn't look like the Cyberpunk 2077 folder (bin\\x64\\oo2ext_7_win64.dll is missing)."
        )
    shutil.copy(src, OODLE)


# ----------------------------------------------------------------------------- templates
def templates_missing(tdir):
    return [n for n in TEMPLATES if not os.path.isfile(os.path.join(tdir, n + ".json"))]


def import_templates(wk, src, tdir, log=print):
    """src = Fun Tattoos Angel .archive, or a folder with the 8 serialized JSONs (+ optional base .xbm)."""
    os.makedirs(tdir, exist_ok=True)
    if os.path.isdir(src):
        found = {}
        for d, _, files in os.walk(src):
            for f in files:
                found.setdefault(f.lower(), os.path.join(d, f))
        missing = [n for n in TEMPLATES if n.lower() + ".json" not in found]
        if missing:
            raise UserError(
                "This folder is missing these template files:\n  "
                + "\n  ".join(n + ".json" for n in missing)
            )
        for f in [n + ".json" for n in TEMPLATES] + list(set(BASE_XBM.values())):
            if f.lower() in found:  # base .xbm is optional (only PNG tattoos need it)
                shutil.copy(found[f.lower()], os.path.join(tdir, f))
        log("Templates copied from the folder.")
        return
    if not src.lower().endswith(".archive"):
        raise UserError(
            "Please pick the Fun Tattoos .archive file (or a folder of JSON files)."
        )
    with tempfile.TemporaryDirectory(prefix="tattoo_tpl_") as tmp:
        log("Extracting templates from %s ..." % os.path.basename(src))
        wk.unbundle(src, os.path.join(tmp, "raw"), FUN_REGEX)
        files = {}
        for d, _, fs in os.walk(os.path.join(tmp, "raw")):
            for f in fs:
                files[f] = os.path.join(d, f)
        missing = [
            n for n in TEMPLATES + sorted(set(BASE_XBM.values())) if n not in files
        ]
        if missing:
            raise UserError(
                "This doesn't look like the Fun Tattoos archive for the Angel body.\n"
                "Pick fun_tattoos_angel_funsix.archive (from the Fun Tattoos download).\nMissing inside:\n  "
                + "\n  ".join(missing)
            )
        flat = os.path.join(tmp, "flat")
        os.makedirs(flat)
        for n in TEMPLATES:
            shutil.copy(files[n], flat)
        wk.run("convert", "serialize", flat, "-o", tdir)
        for n in set(BASE_XBM.values()):
            shutil.copy(files[n], tdir)
    if templates_missing(tdir):
        raise UserError(
            "WolvenKit did not convert all templates: "
            + ", ".join(templates_missing(tdir))
        )
    log("Templates ready (%d files)." % len(TEMPLATES))


# ----------------------------------------------------------------------------- tattoo sources
def scan_mod(wk, archive):
    """-> [(depot path, row or 'full')] for the tattoo textures inside a tattoo mod's .archive."""
    return [
        (p, MOD_TEXTURES[p.rsplit("\\", 1)[-1].lower()])
        for p in wk.listing(archive)
        if p.rsplit("\\", 1)[-1].lower() in MOD_TEXTURES
    ]


def extract_mod_texture(wk, archive, depot, out):
    name = depot.rsplit("\\", 1)[-1]
    wk.unbundle(
        archive,
        out,
        r"(^|[^a-z0-9_])" + re.escape(name.lower()).replace(r"\.", "[.]") + "$",
    )
    p = os.path.join(out, *depot.split("\\"))
    if not os.path.isfile(p):
        raise UserError(
            "Could not extract %s from %s." % (name, os.path.basename(archive))
        )
    return p


# ----------------------------------------------------------------------------- one mod = one list
class Project:
    """work/<prefix>/: list.json (the tattoo list), textures/, options.json + options.lock.json (build.py)."""

    def __init__(self, base, prefix):
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,23}", prefix or ""):
            raise UserError(
                "Mod name: 2-24 characters, lowercase letters, digits and _ , starting with a letter (e.g. mytat)."
            )
        self.base, self.prefix = base, prefix
        self.dir = os.path.join(base, "work", prefix)
        self.tex = os.path.join(self.dir, "textures")
        self.tattoos, self.alpha = [], 1.0
        try:
            with open(os.path.join(self.dir, "list.json"), encoding="utf-8") as f:
                d = json.load(f)
            self.tattoos, self.alpha = d["tattoos"], d.get("diffuse_alpha", 1.0)
        except FileNotFoundError:
            pass

    def save(self):
        os.makedirs(self.tex, exist_ok=True)
        with open(os.path.join(self.dir, "list.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"diffuse_alpha": self.alpha, "tattoos": self.tattoos}, f, indent=1
            )

    def locked(self):
        """Keys already in a built mod (build.py's options.lock.json): they keep their place forever."""
        try:
            with open(
                os.path.join(self.dir, "options.lock.json"), encoding="utf-8"
            ) as f:
                ids = [i for v in json.load(f).values() for i in v]
        except FileNotFoundError:
            return set()
        return {i[len(self.prefix) + 1 :] for i in ids}

    def file(self, t, preview=False):
        return (
            os.path.join(self.tex, t["preview" if preview else "file"])
            if t.get("preview" if preview else "file")
            else None
        )

    def add(self, label, part, src=None, image=None, preview=None):
        """src = .png/.xbm file to copy, or image = PIL image to save as PNG. Returns the new row."""
        label = label.strip()
        if not label:
            raise UserError("Please give the tattoo a name.")
        if part not in PART_NAME:
            raise UserError("Please pick a body part.")
        keys = {t["key"] for t in self.tattoos} | self.locked()
        key = base = "%s_%s" % (slug(label), part)
        n = 2
        while key in keys:
            key, n = "%s_%d" % (base, n), n + 1
        os.makedirs(self.tex, exist_ok=True)
        ext = ".png" if image is not None else os.path.splitext(src)[1].lower()
        if ext not in (".png", ".xbm"):
            raise UserError("Tattoo pictures must be .png or .xbm files.")
        t = {"key": key, "label": label, "part": part, "file": key + ext}
        if image is not None:
            image.save(self.file(t))
        else:
            shutil.copy(src, self.file(t))
        if preview:
            t["preview"] = key + ".preview.png"
            shutil.copy(preview, self.file(t, True))
        self.tattoos.append(t)
        self.save()
        return t

    def remove(self, key):
        if key in self.locked():
            raise UserError(
                "This tattoo is already part of a built mod, so it can't be removed.\n\n"
                "Saves remember tattoos by their position in the list. Removing one would shift every "
                "tattoo after it, and old saves would suddenly show a different tattoo.\n\n"
                "You can rename it instead."
            )
        t = next(t for t in self.tattoos if t["key"] == key)
        self.tattoos.remove(t)
        for p in (self.file(t), self.file(t, True)):
            if p and os.path.isfile(p):
                os.remove(p)
        self.save()

    def rename(self, key, label):
        if not label.strip():
            raise UserError("The name can't be empty.")
        next(t for t in self.tattoos if t["key"] == key)["label"] = label.strip()
        self.save()

    def options(self):
        root = self.prefix + "/tattoos"
        return {
            "prefix": self.prefix,
            "depot_root": root,
            "diffuse_alpha": round(float(self.alpha), 2),
            "parts": PARTS,
            "options": [
                {
                    "id": "%s_%s" % (self.prefix, t["key"]),
                    "part": t["part"],
                    "label": t["label"],
                    "texture": "%s/textures/%s.xbm" % (root, t["key"]),
                }
                for t in self.tattoos
            ],
        }

    def build(self, wk, tdir, out_dir, log=print):
        """Whole pipeline -> (<prefix>_tattoos.archive, <prefix>_tattoos.archive.xl) in out_dir."""
        if not self.tattoos:
            raise UserError("Add at least one tattoo first.")
        if templates_missing(tdir):
            raise UserError(
                "The templates are not set up yet. Click 'Get templates...' first."
            )
        for t in self.tattoos:
            if not os.path.isfile(self.file(t)):
                raise UserError(
                    "The picture for '%s' is missing:\n%s" % (t["label"], self.file(t))
                )
            if t["file"].endswith(".png") and not os.path.isfile(
                os.path.join(tdir, BASE_XBM[PART_KIND[t["part"]]])
            ):
                raise UserError(
                    "PNG tattoos need a base texture from the Fun Tattoos archive.\n"
                    "Click 'Get templates...' and pick the Fun Tattoos .archive (not a JSON folder)."
                )
        cfg = os.path.join(self.dir, "options.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump(self.options(), f, indent=1)
        work = os.path.join(self.dir, "build")
        jdir = os.path.join(work, "json")
        log("Writing the mod files (build.py) ...")
        buf = (
            io.StringIO()
        )  # build.py prints a long file list; only its summary line goes to the log
        try:
            tsbuild.check_order(
                cfg, {p["id"]: p for p in PARTS}, self.options()["options"]
            )  # before wiping work
            shutil.rmtree(work, ignore_errors=True)
            with contextlib.redirect_stdout(buf):
                xl, textures = tsbuild.build(tdir, jdir, cfg)
            log("  " + buf.getvalue().splitlines()[0])
        except tsbuild.OrderError:
            raise UserError(
                "The tattoo list no longer matches the mod you built before.\n\n"
                "Tattoos that are already in a built mod must stay in the same order (saves remember the "
                "position). Undo the change, or start a new mod with a different mod name."
            )
        except AssertionError as e:
            raise UserError("The build stopped: %s" % e)

        name = self.prefix + "_tattoos"
        proj = os.path.join(work, name)  # pack names the archive after this folder
        # build.py writes every file flat into depot_root; deserialize flattens folders anyway
        rdir = os.path.join(proj, self.prefix, "tattoos")
        os.makedirs(rdir)
        log("Converting to game files ...")
        wk.run(
            "convert",
            "deserialize",
            os.path.join(jdir, self.prefix, "tattoos"),
            "-o",
            rdir,
        )
        raw = os.path.join(work, "raw")
        pngs = 0
        for t in self.tattoos:
            rel = os.path.join(self.prefix, "tattoos", "textures", t["key"])
            os.makedirs(os.path.dirname(os.path.join(proj, rel)), exist_ok=True)
            if t["file"].endswith(".xbm"):
                shutil.copy(self.file(t), os.path.join(proj, rel + ".xbm"))
            else:  # copy a base .xbm, then import the PNG over it keeping its settings
                shutil.copy(
                    os.path.join(tdir, BASE_XBM[PART_KIND[t["part"]]]),
                    os.path.join(proj, rel + ".xbm"),
                )
                os.makedirs(os.path.dirname(os.path.join(raw, rel)), exist_ok=True)
                shutil.copy(self.file(t), os.path.join(raw, rel + ".png"))
                pngs += 1
        if pngs:
            log("Turning %d PNG picture(s) into game textures ..." % pngs)
            out = wk.run(
                "import", raw, "-k", "-o", proj, ok=(0, 3)
            )  # exits 3 after a successful -k import
            if "Imported %d/%d" % (pngs, pngs) not in out:
                raise UserError(
                    "WolvenKit could not import all PNG pictures:\n"
                    + "\n".join(out.strip().splitlines()[-6:])
                )
        log("Packing ...")
        os.makedirs(out_dir, exist_ok=True)
        archive = os.path.join(out_dir, name + ".archive")
        if os.path.exists(archive):
            os.remove(archive)
        wk.run("pack", proj, "-o", out_dir)
        if not os.path.isfile(archive):
            raise UserError("WolvenKit did not create %s." % archive)
        xl_out = os.path.join(out_dir, os.path.basename(xl))
        shutil.copy(xl, xl_out)

        # check: everything build.py wrote + every texture is inside the archive
        want = {
            p[: -len(".json")].lower() for p in _rel_files(jdir) if p.endswith(".json")
        } | {t.lower() for t in textures}
        have = {p.lower() for p in wk.listing(archive)}
        if want - have:
            raise UserError(
                "The packed archive is missing:\n  " + "\n  ".join(sorted(want - have))
            )
        log("Checked: all %d files are in the archive." % len(want))
        return archive, xl_out


def _rel_files(d):
    return [
        os.path.relpath(os.path.join(r, f), d) for r, _, fs in os.walk(d) for f in fs
    ]


def install(files, game):
    if not os.path.isdir(os.path.join(game, "archive", "pc")):
        raise UserError(
            "That doesn't look like the Cyberpunk 2077 folder (there is no archive\\pc inside)."
        )
    mod = os.path.join(game, "archive", "pc", "mod")
    os.makedirs(mod, exist_ok=True)
    for f in files:
        shutil.copy(f, mod)
    return mod


def prepare_source(wk, path, tmp):
    """A picked file -> [(source file, preview png or None, suggested row or 'full' or None, name)]."""
    stem = os.path.splitext(os.path.basename(path))[0]
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        return [(path, path, None, stem)]
    if ext == ".xbm":
        return [
            (
                path,
                wk.to_png(path, tmp),
                MOD_TEXTURES.get(os.path.basename(path).lower()),
                stem,
            )
        ]
    if ext == ".archive":
        found = scan_mod(wk, path)
        if not found:
            raise UserError(
                "No tattoo pictures found in this archive.\nI look for femme_arm_left_01_overlay.xbm, "
                "femme_arm_right_01_overlay.xbm and v_overlay.xbm (what arm and full-body tattoo mods replace)."
            )
        res = []
        for i, (depot, row) in enumerate(found):
            x = extract_mod_texture(wk, path, depot, os.path.join(tmp, str(i)))
            res.append((x, wk.to_png(x, os.path.join(tmp, str(i), "png")), row, stem))
        return res
    raise UserError("Please pick a .png, an .xbm or a tattoo mod's .archive.")


# ----------------------------------------------------------------------------- self-test
def selftest(a):
    base = os.path.abspath(a.selftest)
    exe = a.wk or load_settings().get("wolvenkit")
    wk = WolvenKit(exe)
    assert oodle_ok(), "oo2ext_7_win64.dll missing in %LOCALAPPDATA%"
    tdir = os.path.join(base, "work", "templates")
    import_templates(wk, a.fun, tdir)
    shutil.rmtree(os.path.join(base, "work", "tguitest"), ignore_errors=True)
    p = Project(base, "tguitest")
    tmp = os.path.join(base, "incoming")

    arm = prepare_source(wk, a.arm, os.path.join(tmp, "arm"))
    src, prev, row, name = next(x for x in arm if x[2] in ("left_arm", "right_arm"))
    p.add("Mod Arm", row, src=src, preview=prev)  # xbm copied as is
    p.add("My PNG", "left_arm", src=a.png)  # PNG -> import -k
    body = prepare_source(wk, a.body, os.path.join(tmp, "body"))
    full = next(x for x in body if x[2] in ("full", None))
    parts = split_image(Image.open(full[1]), 0.59)
    for part in SPLIT_PARTS:
        p.add("Body", part, image=parts[part])
    assert [t["part"] for t in p.tattoos] == [
        row,
        "left_arm",
        "torso",
        "legs",
        "chest",
    ], p.tattoos
    p.alpha = 0.8

    out = os.path.join(base, "output")
    archive, xl = p.build(wk, tdir, out)
    listing = wk.listing(archive)
    print("archive contents:", *listing, sep="\n  ")
    xbms = [l for l in listing if l.endswith(".xbm")]
    assert len(xbms) == 5, xbms
    with open(xl, encoding="utf-8") as f:
        xltext = f.read()
    print("archive.xl:\n" + xltext)
    assert (
        xltext
        == "customizations:\n  female: tguitest\\tattoos\\tguitest_tattoos_pwa.inkcharcustomization\n"
    )
    # PNG became a real texture with the PNG's size
    j = os.path.join(base, "chk")
    os.makedirs(j, exist_ok=True)
    png_xbm = os.path.join(
        p.dir,
        "build",
        "tguitest_tattoos",
        "tguitest",
        "tattoos",
        "textures",
        p.tattoos[1]["key"] + ".xbm",
    )
    wk.run("convert", "serialize", png_xbm, "-o", j)
    with open(
        os.path.join(j, os.path.basename(png_xbm) + ".json"), encoding="utf-8"
    ) as f:
        rc = json.load(f)["Data"]["RootChunk"]
    assert (rc["width"], rc["height"]) == Image.open(a.png).size, (
        rc["width"],
        rc["height"],
    )
    with open(os.path.join(p.dir, "options.json"), encoding="utf-8") as f:
        assert json.load(f)["diffuse_alpha"] == 0.8

    # append-only: built rows can't be removed, a reorder is refused with a plain message
    try:
        p.remove(p.tattoos[0]["key"])
        raise AssertionError("removing a built tattoo was allowed")
    except UserError:
        pass
    p.add("New One", "left_arm", src=a.png)
    p.rename(p.tattoos[-1]["key"], "Renamed")
    p.remove(p.tattoos[-1]["key"])  # never built -> allowed
    p.add("New One", "left_arm", src=a.png)
    p.tattoos[1], p.tattoos[-1] = (
        p.tattoos[-1],
        p.tattoos[1],
    )  # new left arm before the built one
    try:
        p.build(wk, tdir, out)
        raise AssertionError("reorder was not refused")
    except UserError as e:
        assert "same order" in str(e), e
    print("SELFTEST OK:", archive)


# ----------------------------------------------------------------------------- window
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
    from PIL import ImageDraw, ImageTk

    class App:
        def __init__(self, root):
            self.root = root
            self.s = load_settings()
            self.q = queue.Queue()
            self.busy = False
            self.tdir = os.path.join(USER, "work", "templates")
            self.out = os.path.join(USER, "output")
            self.last = None  # files of the last build
            self.thumbs = {}
            root.title("Tattoo Switchers %s" % VERSION)

            setup = ttk.LabelFrame(root, text="1. Setup (once)")
            setup.pack(fill="x", padx=8, pady=(8, 4))
            self.wk_var, self.tpl_var = tk.StringVar(), tk.StringVar()
            ttk.Label(setup, text="WolvenKit:").grid(
                row=0, column=0, sticky="w", padx=6, pady=3
            )
            ttk.Label(setup, textvariable=self.wk_var).grid(row=0, column=1, sticky="w")
            ttk.Button(setup, text="Find WolvenKit...", command=self.pick_wk).grid(
                row=0, column=2, padx=6, sticky="e"
            )
            ttk.Label(setup, text="Templates:").grid(
                row=1, column=0, sticky="w", padx=6, pady=3
            )
            ttk.Label(setup, textvariable=self.tpl_var).grid(
                row=1, column=1, sticky="w"
            )
            tb = ttk.Frame(setup)
            tb.grid(row=1, column=2, padx=6, sticky="e")
            ttk.Button(tb, text="Get templates...", command=self.pick_templates).pack(
                side="left"
            )
            ttk.Button(
                tb,
                text="JSON folder...",
                command=lambda: self.pick_templates(folder=True),
            ).pack(side="left", padx=(4, 0))
            setup.columnconfigure(1, weight=1)

            sett = ttk.LabelFrame(root, text="2. Your mod")
            sett.pack(fill="x", padx=8, pady=4)
            ttk.Label(sett, text="Mod name:").pack(side="left", padx=6, pady=4)
            self.prefix_var = tk.StringVar(value=self.s.get("prefix", "mytat"))
            e = ttk.Entry(sett, textvariable=self.prefix_var, width=16)
            e.pack(side="left")
            e.bind("<Return>", lambda _: self.load_project())
            e.bind("<FocusOut>", lambda _: self.load_project())
            ttk.Label(sett, text="(short, lowercase, e.g. mytat)").pack(
                side="left", padx=(4, 20)
            )
            ttk.Label(sett, text="Ink strength:").pack(side="left")
            self.alpha_var = tk.DoubleVar(value=1.0)
            ttk.Scale(
                sett,
                from_=0.3,
                to=1.0,
                variable=self.alpha_var,
                length=160,
                command=self.alpha_changed,
            ).pack(side="left", padx=4)
            self.alpha_lbl = ttk.Label(sett, width=5)
            self.alpha_lbl.pack(side="left")
            ttk.Label(sett, text="(1.0 full colour, 0.6 faded)").pack(side="left")

            lst = ttk.LabelFrame(root, text="3. Tattoos")
            lst.pack(fill="both", expand=True, padx=8, pady=4)
            bar = ttk.Frame(lst)
            bar.pack(fill="x", padx=4, pady=4)
            for text, cmd in (
                ("Add picture (PNG)...", self.add_png),
                ("Add from tattoo mod (.archive / .xbm)...", self.add_mod),
                ("Split full-body picture...", self.add_split),
                ("Rename...", self.rename),
                ("Remove", self.remove),
            ):
                ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 4))
            mid = ttk.Frame(lst)
            mid.pack(fill="both", expand=True, padx=4)
            self.tree = ttk.Treeview(
                mid,
                columns=("name", "part", "pic", "state"),
                show="headings",
                selectmode="browse",
            )
            for c, t, w in (
                ("name", "Name in game", 220),
                ("part", "Body part", 110),
                ("pic", "Picture", 200),
                ("state", "", 140),
            ):
                self.tree.heading(c, text=t)
                self.tree.column(c, width=w, stretch=c != "state")
            self.tree.pack(side="left", fill="both", expand=True)
            sb = ttk.Scrollbar(mid, command=self.tree.yview)
            sb.pack(side="left", fill="y")
            self.tree.configure(yscrollcommand=sb.set)
            self.tree.bind("<<TreeviewSelect>>", lambda _: self.show_preview())
            self.preview = ttk.Label(
                mid, text="(select a tattoo)", anchor="center", width=30
            )
            self.preview.pack(side="left", padx=6)
            ttk.Label(
                lst,
                foreground="#555",
                wraplength=900,
                justify="left",
                text="Tattoos marked 'in built mod' keep their place: they can't be removed or moved, because saves "
                "remember tattoos by position. You can still rename them. New tattoos are always added at the end.",
            ).pack(fill="x", padx=6, pady=(2, 4))

            act = ttk.Frame(root)
            act.pack(fill="x", padx=8, pady=4)
            self.build_btn = ttk.Button(act, text="Build mod", command=self.build)
            self.build_btn.pack(side="left")
            ttk.Button(act, text="Open folder", command=self.open_folder).pack(
                side="left", padx=4
            )
            ttk.Button(act, text="Install to game...", command=self.install).pack(
                side="left"
            )
            self.status = ttk.Label(act, text="")
            self.status.pack(side="left", padx=10)

            self.logbox = tk.Text(
                root, height=9, state="disabled", wrap="word", font=("Consolas", 9)
            )
            self.logbox.pack(fill="both", padx=8, pady=(0, 8))

            self.project = None
            self.refresh_setup()
            self.load_project()
            root.after(100, self.poll)

        # ---- plumbing
        def log(self, msg):  # thread-safe
            self.q.put(("log", msg))

        def poll(self):
            try:
                while True:
                    kind, val = self.q.get_nowait()
                    if kind == "log":
                        self.logbox.configure(state="normal")
                        self.logbox.insert("end", val + "\n")
                        self.logbox.see("end")
                        self.logbox.configure(state="disabled")
                    else:
                        val()
            except queue.Empty:
                pass
            self.root.after(100, self.poll)

        def task(self, label, fn, done=None):
            """Run fn() in a thread (WolvenKit calls take seconds); done(result) back on the UI thread."""
            if self.busy:
                messagebox.showinfo(
                    "Busy", "Please wait until the current step is finished."
                )
                return
            self.busy = True
            self.status.configure(text=label + " ...")
            self.root.configure(cursor="watch")

            def work():
                try:
                    r = fn()
                    ok = lambda: done and done(r)  # noqa: E731
                except UserError as e:
                    self.log("Problem: " + str(e).splitlines()[0])
                    ok = lambda e=e: messagebox.showerror("Tattoo Switchers", str(e))  # noqa: E731
                except (
                    Exception
                ) as e:  # unexpected: full details in the log, short message in the box
                    self.log(traceback.format_exc())
                    ok = lambda e=e: messagebox.showerror(  # noqa: E731
                        "Tattoo Switchers",
                        "Something unexpected went wrong:\n%s\n\nDetails are in the log box."
                        % e,
                    )

                def finish():
                    self.busy = False
                    self.status.configure(text="")
                    self.root.configure(cursor="")
                    ok()

                self.q.put(("call", finish))

            threading.Thread(target=work, daemon=True).start()

        def guard(self, fn, *a):
            try:
                return fn(*a)
            except UserError as e:
                messagebox.showerror("Tattoo Switchers", str(e))

        def wk(self):
            return WolvenKit(self.s.get("wolvenkit"), self.log)

        # ---- setup
        def refresh_setup(self):
            self.wk_var.set(
                self.s.get("wolvenkit") or "not set - click 'Find WolvenKit...'"
            )
            miss = templates_missing(self.tdir)
            self.tpl_var.set(
                "ready"
                if not miss
                else "not set - click 'Get templates...' and pick the Fun Tattoos Angel .archive"
            )

        def pick_wk(self):
            p = filedialog.askopenfilename(
                title="Pick WolvenKit.CLI.exe",
                filetypes=[
                    ("WolvenKit.CLI.exe", "WolvenKit.CLI.exe"),
                    ("Programs", "*.exe"),
                ],
            )
            if not p:
                return
            p = os.path.normpath(p)
            if self.guard(WolvenKit, p, self.log) is None:
                return
            self.s["wolvenkit"] = p
            save_settings(self.s)
            self.refresh_setup()
            self.log("WolvenKit set: " + p)

        def pick_templates(self, folder=False):
            if folder:
                src = filedialog.askdirectory(
                    title="Folder with the 8 template JSON files"
                )
            else:
                src = filedialog.askopenfilename(
                    title="Pick the Fun Tattoos Angel archive (fun_tattoos_angel_funsix.archive)",
                    filetypes=[("Cyberpunk archive", "*.archive")],
                )
            if not src:
                return
            wk = None if folder else self.guard(self.wk)
            if not folder and wk is None:
                return
            self.task(
                "Getting templates",
                lambda: import_templates(
                    wk, os.path.normpath(src), self.tdir, self.log
                ),
                lambda _: self.refresh_setup(),
            )

        # ---- project
        def load_project(self):
            prefix = self.prefix_var.get().strip()
            if self.project and prefix == self.project.prefix:
                return
            p = self.guard(Project, USER, prefix)
            if p is None:
                if self.project:
                    self.prefix_var.set(self.project.prefix)
                return
            if (
                self.project
                and self.project.tattoos
                and not os.path.isfile(os.path.join(p.dir, "list.json"))
            ):
                # new mod name: take the current list along (copied; the old mod stays as it was)
                if messagebox.askyesno(
                    "New mod name",
                    "Start '%s' with the tattoos from '%s'?\n(No = start with an empty list)"
                    % (prefix, self.project.prefix),
                ):
                    shutil.copytree(self.project.tex, p.tex, dirs_exist_ok=True)
                    p.tattoos = [dict(t) for t in self.project.tattoos]
                    p.alpha = self.project.alpha
                p.save()
            self.project = p
            self.s["prefix"] = prefix
            save_settings(self.s)
            self.alpha_var.set(p.alpha)
            self.alpha_lbl.configure(text="%.2f" % p.alpha)
            self.refresh_list()

        def alpha_changed(self, _=None):
            v = round(self.alpha_var.get(), 2)
            self.alpha_lbl.configure(text="%.2f" % v)
            if self.project:
                self.project.alpha = v
                self.project.save()

        def refresh_list(self, select=None):
            self.tree.delete(*self.tree.get_children())
            locked = self.project.locked()
            for t in self.project.tattoos:
                self.tree.insert(
                    "",
                    "end",
                    iid=t["key"],
                    values=(
                        t["label"],
                        PART_NAME[t["part"]],
                        t["file"],
                        "in built mod" if t["key"] in locked else "new",
                    ),
                )
            if select:
                self.tree.selection_set(select)
                self.tree.see(select)
            self.show_preview()

        def selected(self):
            sel = self.tree.selection()
            return next(
                (t for t in self.project.tattoos if sel and t["key"] == sel[0]), None
            )

        def thumb(self, path, size):
            im = Image.open(path).convert("RGBA")
            im.thumbnail((size, size))
            bg = Image.new(
                "RGBA", im.size, (200, 190, 180, 255)
            )  # skin-ish backdrop so ink is visible
            bg.alpha_composite(im)
            return bg

        def show_preview(self):
            t = self.selected()
            path = t and (
                self.project.file(t, True)
                or (t["file"].endswith(".png") and self.project.file(t))
            )
            if not path or not os.path.isfile(path):
                self.preview.configure(
                    image="", text="(no preview)" if t else "(select a tattoo)"
                )
                return
            img = ImageTk.PhotoImage(self.thumb(path, 220))
            self.thumbs["sel"] = img
            self.preview.configure(image=img, text="")

        # ---- adding
        def add_png(self):
            p = filedialog.askopenfilename(
                title="Pick a tattoo picture", filetypes=[("PNG picture", "*.png")]
            )
            if p:
                self.offer([(p, p, None, os.path.splitext(os.path.basename(p))[0])])

        def incoming(self):
            """Scratch folder for extracted textures; added tattoos are copied out of it."""
            d = os.path.join(self.project.dir, "incoming")
            shutil.rmtree(d, ignore_errors=True)
            return d

        def add_mod(self):
            p = filedialog.askopenfilename(
                title="Pick a tattoo mod's .archive (or an .xbm from it)",
                filetypes=[("Tattoo mod", "*.archive *.xbm")],
            )
            if not p:
                return
            wk = self.guard(self.wk)
            if wk:
                tmp = self.incoming()
                self.task(
                    "Reading " + os.path.basename(p),
                    lambda: prepare_source(wk, os.path.normpath(p), tmp),
                    self.offer,
                )

        def add_split(self):
            p = filedialog.askopenfilename(
                title="Pick a full-body tattoo picture (PNG, or v_overlay.xbm / a full-body tattoo mod)",
                filetypes=[("Picture or tattoo mod", "*.png *.xbm *.archive")],
            )
            if not p:
                return
            if p.lower().endswith(".png"):
                return self.offer(
                    [(p, p, "full", os.path.splitext(os.path.basename(p))[0])]
                )
            wk = self.guard(self.wk)
            if wk:
                tmp = self.incoming()
                self.task(
                    "Reading " + os.path.basename(p),
                    lambda: prepare_source(wk, os.path.normpath(p), tmp),
                    lambda items: self.offer(
                        [(s, pv, "full", n) for s, pv, _, n in items]
                    ),
                )

        def offer(self, items):
            """One dialog per found picture. row 'full' -> split dialog."""
            for src, prev, row, name in items:
                if row == "full":
                    self.split_dialog(prev, name)
                else:
                    self.add_dialog(src, prev, row, name)
            self.refresh_list()

        def add_dialog(self, src, prev, row, name):
            d = tk.Toplevel(self.root)
            d.title("Add tattoo")
            d.transient(self.root)
            d.grab_set()
            if prev:
                img = ImageTk.PhotoImage(self.thumb(prev, 200))
                d._img = img
                ttk.Label(d, image=img).grid(row=0, column=0, rowspan=4, padx=8, pady=8)
            ttk.Label(d, text=os.path.basename(src)).grid(
                row=0, column=1, columnspan=2, sticky="w", pady=(8, 0)
            )
            ttk.Label(d, text="Name in game:").grid(row=1, column=1, sticky="w", padx=4)
            nv = tk.StringVar(value=name.replace("_", " ").title())
            ttk.Entry(d, textvariable=nv, width=28).grid(
                row=1, column=2, padx=4, pady=4
            )
            ttk.Label(d, text="Body part:").grid(row=2, column=1, sticky="w", padx=4)
            choices = [PART_NAME[p["id"]] for p in PARTS] + [
                "Full body (split into Torso + Legs + Chest)"
            ]
            pv = tk.StringVar(value=PART_NAME.get(row, ""))
            ttk.Combobox(
                d, textvariable=pv, values=choices, state="readonly", width=40
            ).grid(row=2, column=2, padx=4, pady=4)

            def ok():
                part = next((k for k, v in PART_NAME.items() if v == pv.get()), None)
                if pv.get().startswith("Full body"):
                    d.destroy()
                    return self.split_dialog(prev, nv.get())
                is_png = src.lower().endswith(".png")
                t = self.guard(
                    self.project.add,
                    nv.get(),
                    part,
                    src,
                    None,
                    None if is_png else prev,
                )
                if t:
                    self.log("Added '%s' (%s)." % (t["label"], PART_NAME[part]))
                    d.destroy()

            bb = ttk.Frame(d)
            bb.grid(row=3, column=1, columnspan=2, sticky="e", padx=4, pady=8)
            ttk.Button(bb, text="Add", command=ok).pack(side="left", padx=4)
            ttk.Button(bb, text="Cancel", command=d.destroy).pack(side="left")
            self.root.wait_window(d)

        def split_dialog(self, png, name):
            d = tk.Toplevel(self.root)
            d.title("Split full-body picture")
            d.transient(self.root)
            d.grab_set()
            small = self.thumb(png, 300)
            S = small.size[0]
            top = ttk.Frame(d)
            top.pack(fill="x", padx=8, pady=8)
            ttk.Label(top, text="Name in game:").pack(side="left")
            nv = tk.StringVar(value=name.replace("_", " ").title())
            ttk.Entry(top, textvariable=nv, width=26).pack(side="left", padx=4)
            ttk.Label(top, text="Cut at:").pack(side="left", padx=(16, 0))
            sv = tk.DoubleVar(value=0.59)
            ttk.Scale(
                top,
                from_=0.40,
                to=0.80,
                variable=sv,
                length=180,
                command=lambda _: draw(),
            ).pack(side="left", padx=4)
            sl = ttk.Label(top, width=5)
            sl.pack(side="left")
            ttk.Label(
                d,
                foreground="#555",
                wraplength=760,
                justify="left",
                text="Torso is left of the red line, legs right of it. 0.59 fits the Angel body; only change it "
                "if a design gets cut in the wrong place. Chest = the whole picture, uncut.",
            ).pack(fill="x", padx=8)
            body = ttk.Frame(d)
            body.pack(padx=8, pady=8)
            big = ttk.Label(body)
            big.grid(row=0, column=0, rowspan=2, padx=(0, 10))
            cells, use = {}, {}
            for i, part in enumerate(SPLIT_PARTS):
                f = ttk.Frame(body)
                f.grid(row=0, column=1 + i, padx=4, sticky="n")
                cells[part] = ttk.Label(f)
                cells[part].pack()
                use[part] = tk.BooleanVar(value=True)
                ttk.Checkbutton(
                    f, text="add as " + PART_NAME[part], variable=use[part]
                ).pack()

            def draw():
                s = round(sv.get(), 2)
                sl.configure(text="%.2f" % s)
                im = small.copy()
                x = round(s * S)
                ImageDraw.Draw(im).line(
                    [(x, 0), (x, S)], fill=(230, 0, 0, 255), width=2
                )
                d._imgs = [ImageTk.PhotoImage(im)]
                big.configure(image=d._imgs[0])
                for part, piece in split_image(small, s, S).items():
                    piece = piece.resize((150, 150))
                    d._imgs.append(ImageTk.PhotoImage(piece))
                    cells[part].configure(image=d._imgs[-1])

            def ok():
                parts = [p for p in SPLIT_PARTS if use[p].get()]
                if not parts or not nv.get().strip():
                    return messagebox.showerror(
                        "Tattoo Switchers",
                        "Give it a name and tick at least one part.",
                        parent=d,
                    )
                s = round(sv.get(), 2)
                d.destroy()

                def work():
                    pieces = split_image(Image.open(png), s)
                    return [
                        self.project.add(nv.get(), p, image=pieces[p]) for p in parts
                    ]

                self.task(
                    "Splitting",
                    work,
                    lambda ts: (
                        self.log(
                            "Added '%s' as %s."
                            % (
                                nv.get().strip(),
                                ", ".join(PART_NAME[t["part"]] for t in ts),
                            )
                        ),
                        self.refresh_list(),
                    ),
                )

            draw()
            bb = ttk.Frame(d)
            bb.pack(anchor="e", padx=8, pady=(0, 8))
            ttk.Button(bb, text="Add", command=ok).pack(side="left", padx=4)
            ttk.Button(bb, text="Cancel", command=d.destroy).pack(side="left")
            self.root.wait_window(d)

        def rename(self):
            t = self.selected()
            if not t:
                return messagebox.showinfo("Rename", "Select a tattoo first.")
            n = simpledialog.askstring(
                "Rename", "New name in game:", initialvalue=t["label"], parent=self.root
            )
            if n is not None and self.guard(self.project.rename, t["key"], n) is None:
                self.refresh_list(t["key"])

        def remove(self):
            t = self.selected()
            if not t:
                return messagebox.showinfo("Remove", "Select a tattoo first.")
            if t["key"] not in self.project.locked() and not messagebox.askyesno(
                "Remove", "Remove '%s'?" % t["label"]
            ):
                return
            self.guard(self.project.remove, t["key"])
            self.refresh_list()

        # ---- build / install
        def build(self):
            wk = self.guard(self.wk)
            if not wk:
                return
            if not oodle_ok():
                if not messagebox.askokcancel(
                    "One-time setup",
                    "WolvenKit needs a file from the game (oo2ext_7_win64.dll) to pack textures correctly.\n"
                    "Pick your Cyberpunk 2077 folder and it will be copied to your user folder (nothing in the game is changed).",
                ):
                    return
                g = filedialog.askdirectory(title="Pick the Cyberpunk 2077 folder")
                if not g:
                    return
                self.guard(install_oodle, os.path.normpath(g))
                if not oodle_ok():
                    return
                self.s["game"] = os.path.normpath(g)
                save_settings(self.s)
            p = self.project

            def done(res):
                self.last = res
                self.refresh_list()
                self.log(
                    "Done: %s and %s are in %s"
                    % (*map(os.path.basename, res), self.out)
                )
                messagebox.showinfo(
                    "Tattoo Switchers",
                    "Your mod is ready:\n\n%s\n%s\n\nClick 'Install to game...' or copy both files to Cyberpunk 2077\\archive\\pc\\mod\\."
                    % res,
                )

            self.log("Building %s_tattoos ..." % p.prefix)
            self.task(
                "Building", lambda: p.build(wk, self.tdir, self.out, self.log), done
            )

        def open_folder(self):
            os.makedirs(self.out, exist_ok=True)
            os.startfile(self.out)

        def install(self):
            if not self.last or not all(os.path.isfile(f) for f in self.last):
                return messagebox.showinfo("Install", "Build the mod first.")
            g = filedialog.askdirectory(
                title="Pick the Cyberpunk 2077 folder",
                initialdir=self.s.get("game") or None,
            )
            if not g:
                return
            mod = self.guard(install, self.last, os.path.normpath(g))
            if mod:
                self.s["game"] = os.path.normpath(g)
                save_settings(self.s)
                self.log("Installed into " + mod)
                messagebox.showinfo(
                    "Installed",
                    "Copied both files into\n%s\n\nRemember to remove the tattoo mods you took the designs from."
                    % mod,
                )

    try:  # sharp text on scaled Windows displays
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    if "--smoke" in sys.argv:  # open, draw, close (used by the tests)
        root.after(1500, root.destroy)
    root.mainloop()


def main():
    if Image is None:
        msg = "Pillow is missing. Open a command prompt and run:  pip install pillow"
        try:
            import tkinter.messagebox as mb

            mb.showerror("Tattoo Switchers", msg)
        except Exception:
            pass
        sys.exit(msg)
    if "--selftest" in sys.argv:
        import argparse

        ap = argparse.ArgumentParser()
        for o in ("--selftest", "--fun", "--arm", "--png", "--body"):
            ap.add_argument(o, required=True)
        ap.add_argument("--wk")
        a = ap.parse_args()
        if sys.stdout is None:  # windowed .exe: no console, so log to a file
            os.makedirs(a.selftest, exist_ok=True)
            sys.stdout = sys.stderr = open(
                os.path.join(a.selftest, "selftest.log"),
                "w",
                encoding="utf-8",
                buffering=1,
            )
        try:
            selftest(a)
        except BaseException:
            traceback.print_exc()
            print("SELFTEST FAILED")
            sys.exit(1)
    else:
        run_gui()


if __name__ == "__main__":
    main()
