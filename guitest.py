"""Drives the real Tattoo Separator window like a user would: every button, through the widgets.

  python tattoo_separator_gui.py --guitest <empty scratch dir> --fun <Fun Tattoos Angel .archive>
      --mod <tattoo mod .archive with arm + v_overlay textures> --xbm <arm .xbm> --png <arm .png>
      --wk <a WolvenKit.CLI.exe> [--nomatch <.archive without tattoo textures>]
  (TattooSeparator.exe --guitest ... works the same.)

First run is real: no WolvenKit anywhere (the LOCALAPPDATA paths point into the scratch dir), WolvenKit is
downloaded for real from GitHub once and checked, a network error and a damaged download are simulated.
The game folder is found for the game-file step (only read from); installs go to a fake game folder.

Only file pickers and message boxes are replaced (they return prepared answers; every message text is
logged for review). Everything else is the real window: buttons are found by their text and invoke()d,
dialogs are filled in through their widgets, builds are awaited through the window's own busy state.
Installs go into a fake game folder inside the scratch dir. Writes <scratch>/guitest.log, exits 0 / 1.
"""

import argparse, contextlib, io, json, os, pathlib, shutil, subprocess, sys, threading, time, traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

g = sys.modules["__main__"]  # tattoo_separator_gui (started through its main())
assert hasattr(g, "run_gui"), "start this through tattoo_separator_gui.py --guitest"

LOG = None
MSGS = []  # (kind, title, text) of every message box
FILES = []  # what the next file / folder picker returns
ANSWERS = []  # what the next yes/no box returns (default: yes)
NAMES = []  # what the next rename box returns
OPENED = []  # os.startfile calls
FAILS = []


def log(*a):
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


class Fail(Exception):
    pass


def check(cond, what):
    if not cond:
        raise Fail(what)
    log("  ok:", what)


def patch_dialogs():
    def box(kind, answer):
        def f(title=None, message=None, **kw):
            MSGS.append((kind, title, message))
            log(
                "  MSG %-11s [%s] %s"
                % (kind, title, (message or "").replace("\n", " | "))
            )
            return answer()

        return f

    yes = lambda: ANSWERS.pop(0) if ANSWERS else True  # noqa: E731
    messagebox.showinfo = box("info", lambda: "ok")
    messagebox.showerror = box("error", lambda: "ok")
    messagebox.showwarning = box("warning", lambda: "ok")
    messagebox.askyesno = box("askyesno", yes)
    messagebox.askokcancel = box("askokcancel", yes)

    def pick(**kw):
        if not FILES:
            raise Fail("unexpected file picker: %s" % kw.get("title"))
        p = FILES.pop(0)
        log("  picker [%s] -> %r" % (kw.get("title"), p))
        return p

    filedialog.askopenfilename = filedialog.askdirectory = pick

    def ask(title, prompt, **kw):
        n = NAMES.pop(0)
        log("  ASK [%s] %s -> %r" % (title, prompt, n))
        return n

    simpledialog.askstring = ask
    os.startfile = lambda p: OPENED.append(p)


# ----------------------------------------------------------------------------- driver
def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


class Driver:
    """Runs a generator script inside the window's event loop. The script yields wait conditions;
    clicks that may open a modal dialog are scheduled, never run inside the script."""

    def __init__(self, root, app, script, done):
        self.root, self.app, self.done = root, app, done
        self.gen, self.wait = script(self), None
        root.after(500, self.tick)

    def tick(self):
        try:
            if self.wait:
                cond, until, what = self.wait
                if not cond():
                    if time.time() > until:
                        raise Fail("timed out waiting for " + what)
                    self.root.after(100, self.tick)
                    return
            w = next(self.gen)
            self.wait = (w[0], time.time() + w[1], w[2]) if w else None
            self.root.after(20, self.tick)
        except StopIteration:
            self.done(True)
        except Exception:
            log("FAIL:\n" + traceback.format_exc())
            FAILS.append(traceback.format_exc().strip().splitlines()[-1])
            self.done(False)
            self.root.destroy()

    # ---- helpers for scripts
    def find(self, cls, text=None, top=None):
        return [
            w
            for w in walk(top or self.root)
            if isinstance(w, cls) and (text is None or str(w.cget("text")) == text)
        ]

    def button(self, text, top=None):
        b = self.find(ttk.Button, text, top)
        if len(b) != 1:
            raise Fail("button %r found %d times" % (text, len(b)))
        return b[0]

    def dialogs(self, title=None):
        return [
            w
            for w in self.root.winfo_children()
            if isinstance(w, tk.Toplevel)
            and w.winfo_exists()
            and (title is None or w.title() == title)
        ]

    def click(self, text, top=None, timeout=10):
        """Press a button (scheduled). Waits until its command returned or opened a dialog."""
        b, state, n = self.button(text, top), [], len(self.dialogs())
        log("click %r" % text)

        def press():
            state.append(1)
            b.invoke()
            state.append(2)

        self.root.after(0, press)
        return (
            lambda: len(state) == 2 or (state and len(self.dialogs()) > n),
            timeout,
            "click %r" % text,
        )

    def idle(self, timeout=900, what="the step to finish"):
        a = (
            self.app
        )  # the window's own state: not busy, build button usable, status cleared
        return (
            lambda: (
                not a.busy
                and a.build_btn.instate(["!disabled"])
                and a.status.cget("text") == ""
            ),
            timeout,
            what,
        )

    def dialog(self, title, timeout=600):
        return (lambda: self.dialogs(title), timeout, "dialog %r" % title)

    def pause(self, ms):
        t = time.time() + ms / 1000
        return (lambda: time.time() > t, ms / 1000 + 5, "pause")

    def gone(self, title):
        return (lambda: not self.dialogs(title), 30, "dialog %r to close" % title)


def msgs_since(n):
    return MSGS[n:]


def expect(n, kind, text):
    new = msgs_since(n)
    check(
        any(k == kind and text in (m or "") for k, _, m in new),
        "%s message containing %r (got %s)"
        % (kind, text, [(k, (m or "")[:60]) for k, _, m in new]),
    )


def no_msgs(n, what):
    check(not msgs_since(n), "%s: no message (got %s)" % (what, msgs_since(n)))


def rows(app):
    return [app.tree.item(i, "values") for i in app.tree.get_children()]


def logtext(app):
    return app.logbox.get("1.0", "end")


def guide(app):
    return str(app.guide.cget("text"))


def no_cli(d):
    """The word CLI never shows in the window or its dialogs (labels, buttons, shown values)."""
    texts = [
        str(w.cget("text"))
        for w in walk(d.root)
        if isinstance(w, (ttk.Label, ttk.Button, ttk.LabelFrame))
    ]
    texts += [d.app.wk_var.get(), d.app.tpl_var.get()] + [
        t.title() for t in d.dialogs()
    ]
    check(
        not [t for t in texts if "CLI" in t],
        "no 'CLI' in the window (%d texts)" % len(texts),
    )


REAL_URL = g.WK_URL


# ----------------------------------------------------------------------------- the user session
def session1(a, d):
    app = d.app
    T = a.t
    log("== first start: no WolvenKit anywhere -> asks once, in plain words")
    yield d.dialog("WolvenKit", 10)
    dlg = d.dialogs("WolvenKit")[0]
    ask = " ".join(str(w.cget("text")) for w in d.find(ttk.Label, top=dlg))
    log("  dialog text: " + ask.replace("\n", " | "))
    check(
        "free modding tool (about 45 MB)" in ask
        and "Download it now automatically?" in ask,
        "asks to download",
    )
    check(d.root.title() == "Tattoo Separator 1.2", "window title %r" % d.root.title())
    check(app.wk_var.get().startswith("not set"), "WolvenKit shows 'not set'")
    check(app.tpl_var.get().startswith("not set"), "Fun Tattoos file shows 'not set'")
    check(
        guide(app).startswith("Step 1: WolvenKit - click 'WolvenKit...'"),
        "guide: step 1",
    )
    check(
        app.prefix_var.get() == "mytat" and rows(app) == [],
        "default mod 'mytat', empty list",
    )
    no_cli(d)
    yield d.click("Not now", dlg)
    yield d.gone("WolvenKit")
    check(not app.busy and not app.wk_path(), "'Not now': nothing happens")

    log("== needed by a step -> asked again; download with a network error")
    g.WK_URL = "http://127.0.0.1:9/WolvenKit.Console.zip"  # nothing listens there
    yield d.click("Build mod")
    yield d.dialog("WolvenKit")
    n = len(MSGS)
    yield d.click("Yes, download it", d.dialogs("WolvenKit")[0])
    yield d.idle(120)
    expect(n, "error", "Could not download WolvenKit. Check your internet connection")
    check(not app.wk_path() and not app.busy, "still not set")
    check(
        not os.listdir(os.path.dirname(g.WK_HOME)),
        "nothing left behind after the failed download",
    )

    log(
        "== Fun Tattoos file without WolvenKit -> asked first; 'Not now' opens no file picker"
    )
    n = len(MSGS)
    yield d.click("Fun Tattoos file...")
    yield d.dialog("WolvenKit")
    yield d.click("Not now", d.dialogs("WolvenKit")[0])
    yield d.pause(200)
    no_msgs(n, "'Not now' before the Fun Tattoos file")

    log("== damaged download (checksum)")
    g.WK_URL = pathlib.Path(T["fakezip"]).as_uri()
    yield d.click("WolvenKit...")
    yield d.dialog("WolvenKit")
    n = len(MSGS)
    yield d.click("Yes, download it", d.dialogs("WolvenKit")[0])
    yield d.idle(120)
    expect(n, "error", "The WolvenKit download is damaged")
    check(not os.listdir(os.path.dirname(g.WK_HOME)), "damaged download removed")

    log("== I already have WolvenKit: wrong folder, cancel, the folder, a file in it")
    for pick, what in (
        (T["emptydir"], "wrong folder"),
        ("", "cancel"),
        (T["wkcopy"], "folder"),
        (os.path.join(T["wkcopy"], "WolvenKit.Common.dll"), "a file in the folder"),
    ):
        yield d.click("WolvenKit...")
        yield d.dialog("WolvenKit")
        n = len(MSGS)
        FILES.append(pick)
        yield d.click("I already have WolvenKit", d.dialogs("WolvenKit")[0])
        yield d.pause(300)
        yield d.idle(300)
        if what == "wrong folder":
            expect(n, "error", "No WolvenKit found in")
            check(not app.wk_path(), "wrong folder: not set")
        elif what == "cancel":
            no_msgs(n, "cancelled picker")
        else:
            no_msgs(n, "picked " + what)
            own = os.path.join(g.WK_HOME, "WolvenKit.CLI.exe")
            check(
                app.wk_path() == own and app.wk_var.get() == g.WK_HOME,
                "WolvenKit set from " + what,
            )
            check(
                "Copying your WolvenKit from " + T["wkcopy"] in logtext(app),
                "copied into our own folder",
            )
            mine, orig = (
                os.path.join(x, "appsettings.json")
                for x in (T["wkcopy"], os.path.dirname(os.path.abspath(a.wk)))
            )
            with open(mine, "rb") as f1, open(orig, "rb") as f2:
                check(
                    f1.read() == f2.read(),
                    "the user's own WolvenKit settings are untouched",
                )
    check(
        guide(app).startswith(
            "Step 1: WolvenKit done     Step 2: Fun Tattoos file - click"
        ),
        "guide: step 2",
    )
    yield d.click("WolvenKit...")
    yield d.dialog("WolvenKit")
    yield d.click("Not now", d.dialogs("WolvenKit")[0])
    yield d.pause(200)
    check(
        app.wk_path() == os.path.join(g.WK_HOME, "WolvenKit.CLI.exe"),
        "'Not now' keeps it",
    )
    shutil.rmtree(g.WK_HOME)  # the real download below starts from nothing

    log("== the real download from GitHub")
    g.WK_URL = REAL_URL
    yield d.click("WolvenKit...")
    yield d.dialog("WolvenKit")
    n = len(MSGS)
    yield d.click("Yes, download it", d.dialogs("WolvenKit")[0])
    seen = []
    yield (
        lambda: seen.append(app.status.cget("text")) or "%" in seen[-1] or not app.busy,
        300,
        "download progress",
    )
    log("  status while downloading: " + " / ".join(dict.fromkeys(seen)))
    yield d.idle(900, "the download")
    no_msgs(n, "real download")
    own = os.path.join(g.WK_HOME, "WolvenKit.CLI.exe")
    check(app.wk_path() == own, "downloaded WolvenKit set")
    check(
        "Download checked (checksum OK)" in logtext(app)
        and "WolvenKit is ready." in logtext(app),
        "checksum OK and it starts",
    )
    v = subprocess.run(
        [own, "--version"],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout.strip()
    check(v.startswith(g.WK_VERSION), "downloaded WolvenKit reports %s" % v)
    check(
        sorted(os.listdir(os.path.dirname(g.WK_HOME))) == ["wolvenkit"],
        "no download leftovers",
    )
    no_cli(d)

    log("== unexpected error in a callback -> log box + plain message")
    n = len(MSGS)
    d.root.after(0, lambda: 1 / 0)
    yield d.pause(300)
    expect(n, "error", "Something unexpected went wrong")
    check("ZeroDivisionError" in logtext(app), "traceback is in the log box")
    a.expected_tracebacks += 1

    log("== Get templates: wrong inputs, then the real archive")
    n = len(MSGS)
    FILES.append(T["txt"])
    yield d.click("Fun Tattoos file...")
    yield d.idle()
    expect(n, "error", "Please pick the Fun Tattoos .archive file")
    n = len(MSGS)
    FILES.append(T["mod"])
    yield d.click("Fun Tattoos file...")
    yield d.idle()
    expect(n, "error", "doesn't look like the Fun Tattoos archive")
    n = len(MSGS)
    FILES.append(T["fakearchive"])
    yield d.click("Fun Tattoos file...")
    yield d.idle()
    expect(n, "error", "WolvenKit could not")
    n = len(MSGS)
    FILES.append(a.fun)
    yield d.click("Fun Tattoos file...")
    check(app.build_btn.instate(["disabled"]), "buttons disabled while a step runs")
    yield d.idle(600)
    no_msgs(n, "templates from the real archive")
    check(app.tpl_var.get() == "ready", "templates ready")
    check(
        guide(app).endswith("Step 3: Tattoos - add tattoos with the buttons below"),
        "guide: step 3",
    )

    log("== JSON folder")
    n = len(MSGS)
    FILES.append(T["emptydir"])
    yield d.click("JSON folder...")
    yield d.idle()
    expect(n, "error", "This folder is missing these template files")
    jdir = os.path.join(a.base, "json templates Ä")
    shutil.copytree(app.tdir, jdir, dirs_exist_ok=True)
    n = len(MSGS)
    FILES.append(jdir)
    yield d.click("JSON folder...")
    yield d.idle()
    no_msgs(n, "JSON folder")
    check("Templates copied from the folder." in logtext(app), "JSON folder copied")

    log("== mod name")
    e = app.prefix_entry

    def type_name(text):
        e.delete(0, "end")
        e.insert(0, text)
        e.focus_force()
        e.event_generate("<Return>")

    for bad in ("", "My Tat!", "täto", "x"):
        n = len(MSGS)
        type_name(bad)
        yield d.pause(100)
        expect(n, "error", "Mod name: 2-24 characters")
        check(len(msgs_since(n)) == 1, "only one message for %r" % bad)
        check(app.prefix_var.get() == "mytat", "name went back to 'mytat'")
    n = len(MSGS)
    type_name("TGUI1")
    yield d.pause(100)
    no_msgs(n, "mod name TGUI1")
    check(
        app.project.prefix == "tgui1" and app.prefix_var.get() == "tgui1",
        "name lowercased and loaded",
    )

    log("== ink strength")
    app.alpha_scale.set(0.8)
    yield d.pause(100)
    check(
        app.alpha_lbl.cget("text") == "0.80" and app.project.alpha == 0.8,
        "ink 0.80 shown and saved",
    )

    log("== Add picture (PNG)")
    n = len(MSGS)
    FILES.append("")
    yield d.click("Add picture (PNG)...")
    no_msgs(n, "cancelled picker")
    FILES.append(T["corrupt"])
    yield d.click("Add picture (PNG)...")
    expect(n, "error", "Can't read this picture")
    check(not d.dialogs(), "no dialog for a broken picture")
    FILES.append(T["png"])
    yield d.click("Add picture (PNG)...")
    yield d.dialog("Add tattoo")
    dlg = d.dialogs("Add tattoo")[0]
    n = len(MSGS)
    yield d.click("Add", dlg)
    expect(n, "error", "Please pick a body part")
    d.find(ttk.Combobox, top=dlg)[0].set("Left Arm")
    ent = [w for w in d.find(ttk.Entry, top=dlg) if not isinstance(w, ttk.Combobox)][0]
    ent.delete(0, "end")
    n = len(MSGS)
    yield d.click("Add", dlg)
    expect(n, "error", "Please give the tattoo a name")
    ent.insert(0, "Arm Tätowierung")
    yield d.click("Add", dlg)
    yield d.gone("Add tattoo")
    check(
        rows(app)[-1][:2] == ("Arm Tätowierung", "Left Arm"), "PNG tattoo in the list"
    )

    log("== Add from tattoo mod: .xbm")
    FILES.append(T["xbm"])
    yield d.click("Add from tattoo mod (.archive / .xbm)...")
    yield d.dialog("Add tattoo")
    dlg = d.dialogs("Add tattoo")[0]
    check(
        d.find(ttk.Combobox, top=dlg)[0].get() == "Right Arm",
        "body part suggested: Right Arm",
    )
    yield d.click("Add", dlg)
    yield d.gone("Add tattoo")
    yield d.idle()
    check(
        rows(app)[-1][1] == "Right Arm" and rows(app)[-1][2].endswith(".xbm"),
        "xbm tattoo in the list",
    )

    log("== Add from tattoo mod: .archive (2 arms + full body)")
    FILES.append(T["mod"])
    yield d.click("Add from tattoo mod (.archive / .xbm)...")
    yield d.dialog("Add tattoo")
    dlg = d.dialogs("Add tattoo")[0]
    ent = [w for w in d.find(ttk.Entry, top=dlg) if not isinstance(w, ttk.Combobox)][0]
    ent.delete(0, "end")
    ent.insert(0, "Mod Left")
    yield d.click("Add", dlg)
    yield d.pause(300)
    yield d.dialog("Add tattoo")  # second arm: cancel
    yield d.click("Cancel", d.dialogs("Add tattoo")[0])
    yield d.dialog("Split full-body picture")
    sd = d.dialogs("Split full-body picture")[0]
    d.find(ttk.Scale, top=sd)[0].set(0.62)
    yield d.pause(200)
    check(
        any(w.cget("text") == "0.62" for w in d.find(ttk.Label, top=sd)),
        "cut slider moved to 0.62",
    )
    [c for c in d.find(ttk.Checkbutton, top=sd) if c.cget("text") == "add as Chest"][
        0
    ].invoke()
    yield d.click("Add", sd)
    yield d.gone("Split full-body picture")
    yield d.idle()
    parts = [r[1] for r in rows(app)]
    check(
        parts[-3:] == ["Left Arm", "Torso", "Legs"],
        "archive gave Left Arm + Torso + Legs (got %s)" % parts,
    )
    check("Chest" not in parts, "unticked Chest not added")

    if T.get("nomatch"):
        n = len(MSGS)
        FILES.append(T["nomatch"])
        yield d.click("Add from tattoo mod (.archive / .xbm)...")
        yield d.idle()
        expect(n, "error", "No tattoo pictures found in this archive")
    n = len(MSGS)
    FILES.append(T["badxbm"])
    yield d.click("Add from tattoo mod (.archive / .xbm)...")
    yield d.idle()
    expect(n, "error", "WolvenKit could not")

    log("== Split full-body picture (PNG)")
    FILES.append(T["body"])
    yield d.click("Split full-body picture...")
    yield d.dialog("Split full-body picture")
    sd = d.dialogs("Split full-body picture")[0]
    for c in d.find(ttk.Checkbutton, top=sd):
        c.invoke()  # all off
    n = len(MSGS)
    yield d.click("Add", sd)
    expect(n, "error", "tick at least one part")
    [c for c in d.find(ttk.Checkbutton, top=sd) if c.cget("text") == "add as Torso"][
        0
    ].invoke()
    ent = d.find(ttk.Entry, top=sd)[0]
    ent.delete(0, "end")
    n = len(MSGS)
    yield d.click("Add", sd)
    expect(n, "error", "Give it a name")
    ent.insert(0, "Ganzkörper")
    yield d.click("Add", sd)
    yield d.gone("Split full-body picture")
    yield d.idle()
    check(rows(app)[-1][:2] == ("Ganzkörper", "Torso"), "split PNG added as Torso")

    log(
        "== Split full-body picture from a mod archive (3 split dialogs, all cancelled)"
    )
    count = len(rows(app))
    FILES.append(T["mod"])
    yield d.click("Split full-body picture...")
    for _ in range(3):
        yield d.dialog("Split full-body picture")
        yield d.click("Cancel", d.dialogs("Split full-body picture")[0])
        yield d.pause(300)
    yield d.idle()
    check(len(rows(app)) == count, "cancelled split dialogs added nothing")

    log("== Rename")
    app.tree.selection_set(())
    n = len(MSGS)
    yield d.click("Rename...")
    expect(n, "info", "Select a tattoo")
    first = app.tree.get_children()[0]
    app.tree.selection_set(first)
    NAMES.extend(["   ", None, "Arm Renamed"])
    n = len(MSGS)
    yield d.click("Rename...")
    expect(n, "error", "The name can't be empty")
    yield d.click("Rename...")
    check(rows(app)[0][0] == "Arm Tätowierung", "cancelled rename keeps the name")
    yield d.click("Rename...")
    check(rows(app)[0][0] == "Arm Renamed", "renamed")

    log("== Remove (new tattoo)")
    last = app.tree.get_children()[-1]
    count = len(rows(app))
    app.tree.selection_set(last)
    ANSWERS.append(False)
    yield d.click("Remove")
    check(len(rows(app)) == count, "'No' keeps it")
    app.tree.selection_set(last)
    yield d.click("Remove")
    check(len(rows(app)) == count - 1, "removed")

    log("== Help")
    yield d.click("Help")
    yield d.dialog("Tattoo Separator - Help")
    h = d.dialogs("Tattoo Separator - Help")[0]
    text = d.find(tk.Text, top=h)[0].get("1.0", "end")
    for s in (
        "Steps, in order",
        "33230",
        "Fun Tattoos Angel Body",
        "only for a female V with the Angel body",
        "red line",
        "add, never remove",
        "Yes, download it",
        "I already have WolvenKit",
        "Fun Tattoos file...",
        "IMPORTANT: remove the original tattoo mods",
    ):
        check(s.lower() in text.lower(), "help mentions %r" % s)
    check("CLI" not in text, "help never says CLI")
    yield d.click("Close", h)
    yield d.gone("Tattoo Separator - Help")

    log("== Install / Open folder before building")
    n = len(MSGS)
    yield d.click("Install to game...")
    expect(n, "info", "Build the mod first")
    yield d.click("Open folder")
    check(OPENED and OPENED[-1] == app.out, "Open folder opens the output folder")

    log("== Build (with the one-time game-file step)")
    check(guide(app).endswith("Step 4: Build - click 'Build mod'"), "guide: step 4")
    real_oodle, g.OODLE = (
        g.OODLE,
        os.path.join(a.base, "oodle test Ä", "oo2ext_7_win64.dll"),
    )
    os.makedirs(os.path.dirname(g.OODLE), exist_ok=True)
    real_find, g.find_game = g.find_game, lambda: None  # first: game not found -> asks
    try:
        n = len(MSGS)
        ANSWERS.append(False)
        yield d.click("Build mod")
        expect(n, "askokcancel", "could not find your game by itself")
        check(not app.busy, "cancel: no build")
        n = len(MSGS)
        FILES.append(a.base)
        yield d.click("Build mod")
        expect(n, "error", "doesn't look like the Cyberpunk 2077 folder")
        check(not app.busy, "wrong folder: no build")
        g.find_game = (
            real_find  # now the real search finds the installed game (only read from)
        )
        game = g.find_game()
        check(game and g.is_game_dir(game), "game found by itself: %s" % game)
        n = len(MSGS)
        yield d.click("Build mod")
        no_msgs(n, "game found: nothing asked")
        check(os.path.isfile(g.OODLE), "game file copied (to the test location)")
        check(app.s.get("game") == game, "game folder remembered")
    finally:
        g.OODLE, g.find_game = real_oodle, real_find
    check(
        app.busy and app.build_btn.instate(["disabled"]),
        "building: Build button disabled",
    )
    yield d.click("Build mod")  # second press while building
    yield d.click("Add picture (PNG)...")  # disabled: must not open a picker
    yield d.pause(400)  # log lines reach the box through the 100 ms queue poll
    check(
        logtext(app).count("Building tgui1_tattoos") == 1, "second Build press ignored"
    )
    n = len(MSGS)
    yield d.idle(1200, "the first build")
    expect(n, "info", "Your mod is ready")
    expect(n, "info", "remove the original tattoo mods you took the designs from")
    check(
        all(r[3] == "in built mod" for r in rows(app)),
        "all tattoos marked 'in built mod'",
    )
    archive = os.path.join(app.out, "tgui1_tattoos.archive")
    check(
        os.path.isfile(archive) and os.path.isfile(archive + ".xl"),
        "both files in the output folder",
    )

    log("== Remove a built tattoo")
    app.tree.selection_set(app.tree.get_children()[0])
    n = len(MSGS)
    yield d.click("Remove")
    expect(n, "error", "already part of a built mod")
    check(len(rows(app)) == len(app.project.tattoos), "still there")

    log("== Open folder, Install to game")
    yield d.click("Open folder")
    check(OPENED[-1] == app.out, "Open folder")
    n = len(MSGS)
    FILES.append("")
    yield d.click("Install to game...")
    no_msgs(n, "cancelled install")
    FILES.append(a.base)
    yield d.click("Install to game...")
    expect(n, "error", "doesn't look like the Cyberpunk 2077 folder")
    n = len(MSGS)
    FILES.append(T["game"])
    yield d.click("Install to game...")
    expect(n, "info", "remove the original tattoo mods you took the designs from")
    check(not [m for m in msgs_since(n) if m[0] == "warning"], "source mod not installed: not listed")
    check(guide(app).endswith("Next: click 'Install to game...'"), "guide: install")
    mod = os.path.join(T["game"], "archive", "pc", "mod")
    src_name = os.path.basename(T["mod"])
    check(app.project.sources == [src_name], "tattoo mod remembered as a source: %s" % app.project.sources)

    log("== Install while the source tattoo mod is still in the game (subfolder, other case)")
    left = os.path.join(mod, "Unter Ordner", src_name.upper())
    os.makedirs(os.path.dirname(left))
    shutil.copy(T["mod"], left)
    n = len(MSGS)
    FILES.append(T["game"])
    yield d.click("Install to game...")
    expect(n, "warning", "These tattoo mods are still installed and will paint over your new tattoos")
    expect(n, "warning", os.path.join("Unter Ordner", src_name.upper()))
    expect(n, "warning", "Nothing was deleted")
    check(os.path.isfile(left), "nothing deleted")
    os.remove(left)
    check(
        os.path.isfile(os.path.join(mod, "tgui1_tattoos.archive"))
        and os.path.isfile(os.path.join(mod, "tgui1_tattoos.archive.xl")),
        "both files in the fake game's archive\\pc\\mod",
    )

    log("== add one more, build again (append)")
    FILES.append(T["png"])
    yield d.click("Add picture (PNG)...")
    yield d.dialog("Add tattoo")
    dlg = d.dialogs("Add tattoo")[0]
    d.find(ttk.Combobox, top=dlg)[0].set("Left Arm")
    ent = [w for w in d.find(ttk.Entry, top=dlg) if not isinstance(w, ttk.Combobox)][0]
    ent.delete(0, "end")
    ent.insert(0, "Second Arm")
    yield d.click("Add", dlg)
    yield d.gone("Add tattoo")
    check(rows(app)[-1][3] == "new", "new tattoo marked 'new'")
    n = len(MSGS)
    yield d.click("Build mod")
    yield d.idle(1200, "the second build")
    expect(n, "info", "Your mod is ready")
    key = app.project.tattoos[-1]["key"]
    listing = g.WolvenKit(app.wk_path(), lambda m: None).listing(archive)
    check(any(key in l for l in listing), "new tattoo's texture is in the archive")
    check(all(r[3] == "in built mod" for r in rows(app)), "all built")

    log("== reorder (list edited by hand) is refused")
    ts = app.project.tattoos
    i = next(k for k, t in enumerate(ts) if t["part"] == "left_arm")
    ts[i], ts[-1] = ts[-1], ts[i]
    app.project.save()
    n = len(MSGS)
    yield d.click("Build mod")
    yield d.idle()
    expect(n, "error", "must stay in the same order")
    ts[i], ts[-1] = ts[-1], ts[i]
    app.project.save()

    log("== switch mod name")
    built = len(rows(app))
    n = len(MSGS)
    ANSWERS.append(True)
    type_name("tgui2")
    yield d.pause(200)
    expect(n, "askyesno", "Start the new mod 'tgui2' with the tattoos from 'tgui1'")
    check(
        len(rows(app)) == built and all(r[3] == "new" for r in rows(app)),
        "list copied, all 'new'",
    )
    n = len(MSGS)
    ANSWERS.append(False)
    type_name("tgui3")
    yield d.pause(200)
    expect(n, "askyesno", "tgui3")
    check(rows(app) == [], "'No' starts empty")
    n = len(MSGS)
    type_name("tgui2")
    yield d.pause(200)
    no_msgs(n, "existing mod name")
    os.remove(app.project.file(app.project.tattoos[0]))
    n = len(MSGS)
    yield d.click("Build mod")
    yield d.idle()
    expect(n, "error", "The picture for 'Arm Renamed' is missing")
    bad = os.path.join(g.USER, "work", "tbroken")
    os.makedirs(bad, exist_ok=True)
    with open(os.path.join(bad, "list.json"), "w") as f:
        f.write("{not json")
    n = len(MSGS)
    type_name("tbroken")
    yield d.pause(200)
    expect(n, "error", "is damaged")
    check(app.prefix_var.get() == "tgui2", "name went back")
    n = len(MSGS)
    type_name("tgui1")
    yield d.pause(200)
    no_msgs(n, "back to tgui1")
    check(len(rows(app)) == built, "tgui1 list back")

    check(
        logtext(app).count("Traceback") == a.expected_tracebacks,
        "no unexpected tracebacks in the log box",
    )
    log("== close the window (title bar X)")
    d.root.tk.call(d.root.protocol("WM_DELETE_WINDOW"))


def session2(a, d):
    app = d.app
    log("== restart: list and setup come back")
    check(app.prefix_var.get() == "tgui1", "mod name remembered")
    check(
        len(rows(app)) == a.built and all(r[3] == "in built mod" for r in rows(app)),
        "list reloaded",
    )
    refit = os.path.dirname(g.REFITTER_WK[0])
    check(app.tpl_var.get() == "ready", "Fun Tattoos file remembered")
    yield d.pause(800)
    check(not d.dialogs("WolvenKit"), "Outfit Refitter's WolvenKit: nothing asked")
    check(
        app.wk_var.get() == refit and app.wk_path() == g.REFITTER_WK[0],
        "Outfit Refitter's WolvenKit used",
    )
    check(
        "Using the WolvenKit that Outfit Refitter downloaded" in logtext(app),
        "log says so",
    )
    check(app.alpha_lbl.cget("text") == "0.80", "ink remembered")
    log("== Install right after a restart (no rebuild)")
    n = len(MSGS)
    FILES.append(a.t["game"])
    yield d.click("Install to game...")
    expect(n, "info", "Copied both files")
    log("== WolvenKit gone missing (and no other copy) -> asked again")
    app.s["wolvenkit"] = os.path.join(a.base, "gone", "WolvenKit.CLI.exe")
    real_refit, g.REFITTER_WK = g.REFITTER_WK, []
    n = len(MSGS)
    yield d.click("Build mod")
    yield d.dialog("WolvenKit")
    yield d.click("Not now", d.dialogs("WolvenKit")[0])
    yield d.pause(200)
    no_msgs(n, "'Not now'")
    check(not app.busy, "no build")
    g.REFITTER_WK = real_refit
    app.s["wolvenkit"] = g.REFITTER_WK[0]
    check("Traceback" not in logtext(app), "no tracebacks in the log box")
    d.root.tk.call(d.root.protocol("WM_DELETE_WINDOW"))


def slow_server():
    """A local server that sends a big download slowly (a fast line could finish GitHub's before the close)."""
    import http.server

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(200 << 20))
            self.end_headers()
            with contextlib.suppress(OSError):
                for _ in range(200):
                    self.wfile.write(b"x" * (1 << 20))
                    time.sleep(0.2)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    srv.handle_error = lambda *a: None
    threading.Thread(target=srv.serve_forever, name="slowserver", daemon=True).start()
    return "http://127.0.0.1:%d/WolvenKit.zip" % srv.server_address[1]


def session_close_download(a, d):
    """Separate process: start the WolvenKit download, then close the window."""
    app = d.app
    yield d.click("WolvenKit...")
    yield d.dialog("WolvenKit")
    yield d.click("Yes, download it", d.dialogs("WolvenKit")[0])
    yield (lambda: "%" in app.status.cget("text"), 300, "download progress")
    a.workers = [
        t for t in threading.enumerate() if "(_work)" in t.name
    ]  # the download thread
    check(len(a.workers) == 1, "one download thread running")
    n = len(MSGS)
    ANSWERS.append(False)
    d.root.tk.call(d.root.protocol("WM_DELETE_WINDOW"))
    expect(n, "askyesno", "A step is still running")
    check(d.root.winfo_exists(), "'No' keeps the window")
    log("closing during the download")
    d.root.tk.call(d.root.protocol("WM_DELETE_WINDOW"))


def session_close(a, d):
    """Separate process: start a build, then close the window while WolvenKit runs."""
    app = d.app
    e = app.prefix_entry
    e.delete(0, "end")
    e.insert(0, "tclose")
    e.event_generate("<Return>")
    yield d.pause(200)
    FILES.append(a.t["png"])
    yield d.click("Add picture (PNG)...")
    yield d.dialog("Add tattoo")
    dlg = d.dialogs("Add tattoo")[0]
    d.find(ttk.Combobox, top=dlg)[0].set("Right Arm")
    yield d.click("Add", dlg)
    yield d.gone("Add tattoo")
    yield d.click("Build mod")
    yield (lambda: g.RUNNING, 300, "WolvenKit to run")
    check(app.busy, "build running")
    n = len(MSGS)
    ANSWERS.append(False)
    d.root.tk.call(d.root.protocol("WM_DELETE_WINDOW"))
    expect(n, "askyesno", "A step is still running")
    check(d.root.winfo_exists(), "'No' keeps the window")
    log("closing during the build")
    d.root.tk.call(d.root.protocol("WM_DELETE_WINDOW"))


# ----------------------------------------------------------------------------- setup + main
def make_inputs(a):
    from PIL import Image

    b = a.base
    t = {}
    inp = os.path.join(b, "Eingabe Dateien")
    os.makedirs(inp, exist_ok=True)
    t["png"] = os.path.join(inp, "Arm Tätowierung.png")
    shutil.copy(a.png, t["png"])
    t["xbm"] = os.path.join(
        inp, os.path.basename(a.xbm)
    )  # keeps femme_arm_..._overlay.xbm name
    shutil.copy(a.xbm, t["xbm"])
    t["mod"] = os.path.join(inp, "Full Body Tätowierung mod.archive")
    shutil.copy(a.mod, t["mod"])
    if a.nomatch:
        t["nomatch"] = os.path.join(inp, "no tattoos here.archive")
        shutil.copy(a.nomatch, t["nomatch"])
    t["txt"] = os.path.join(inp, "readme.txt")
    t["corrupt"] = os.path.join(inp, "kaputt.png")
    t["fakearchive"] = os.path.join(inp, "kaputt.archive")
    t["badxbm"] = os.path.join(inp, "kaputt.xbm")
    for k in ("txt", "corrupt", "fakearchive", "badxbm"):
        with open(t[k], "wb") as f:
            f.write(b"this is not a real file " * 20)
    t["body"] = os.path.join(inp, "Ganzkörper.png")
    im = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    im.paste((20, 20, 120, 255), (100, 50, 400, 450))
    im.save(t["body"])
    t["emptydir"] = os.path.join(inp, "leerer Ordner")
    os.makedirs(t["emptydir"], exist_ok=True)
    t["fakezip"] = os.path.join(inp, "kaputt WolvenKit.zip")
    with open(t["fakezip"], "wb") as f:
        f.write(b"not the real WolvenKit " * 50)
    t["wkcopy"] = os.path.join(b, "Mein WolvenKit Ä")  # "I already have WolvenKit"
    shutil.copytree(os.path.dirname(os.path.abspath(a.wk)), t["wkcopy"])
    t["game"] = os.path.join(b, "fake game Ä", "Cyberpunk 2077")
    os.makedirs(os.path.join(t["game"], "archive", "pc"), exist_ok=True)
    os.makedirs(os.path.join(t["game"], "bin", "x64"), exist_ok=True)
    if os.path.isfile(
        g.OODLE
    ):  # stands in for the game's DLL (copied from the user folder)
        shutil.copy(g.OODLE, os.path.join(t["game"], "bin", "x64"))
    return t


def run_session(a, script):
    result = []
    g.run_gui(
        lambda root, app: Driver(root, app, lambda d: script(a, d), result.append)
    )
    return bool(result and result[0])


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--guitest")
    ap.add_argument("--guitest-close")
    ap.add_argument("--during", default="build")
    ap.add_argument("--fun")
    ap.add_argument("--mod")
    ap.add_argument("--xbm")
    ap.add_argument("--png")
    ap.add_argument("--nomatch")
    ap.add_argument("--wk", default=g.load_settings().get("wolvenkit"))
    a = ap.parse_args()
    closing = bool(a.guitest_close)
    a.base = os.path.abspath(a.guitest_close or a.guitest)
    os.makedirs(a.base, exist_ok=True)
    LOG = open(
        os.path.join(a.base, "guitest_close.log" if closing else "guitest.log"),
        "w",
        encoding="utf-8",
    )
    # anything Python or Tk prints to stderr (thread errors, "Exception in Tkinter callback") is a failure
    err = io.StringIO()
    sys.stderr = err
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    g.USER = os.path.join(a.base, "app folder Ä")
    g.SETTINGS = os.path.join(g.USER, "gui_settings.json")
    os.makedirs(g.USER, exist_ok=True)
    # %LOCALAPPDATA% stand-in: our WolvenKit download and Outfit Refitter's copy live here
    local = os.path.join(a.base, "Local AppData Ä")
    g.WK_HOME = os.path.join(local, "TattooSeparator", "wolvenkit")
    g.REFITTER_WK = [
        os.path.join(local, n, "wolvenkit", "WolvenKit.CLI.exe")
        for n in ("OutfitRefitter", "BodyRefitter")
    ]
    if closing and a.during == "download":
        g.WK_HOME = os.path.join(local, "close test", "wolvenkit")
        g.WK_URL = slow_server()
    os.makedirs(os.path.dirname(g.WK_HOME), exist_ok=True)
    patch_dialogs()
    a.expected_tracebacks = 0
    ok = True
    try:
        if not closing:
            log("== renamed from Tattoo Switchers: old folders are taken over")
            r = os.path.join(a.base, "rename Ä")
            old, new = os.path.join(r, "Local", "TattooSwitcher"), os.path.join(r, "Local", "TattooSeparator")
            os.makedirs(os.path.join(old, "wolvenkit"))
            check(g.move_old_folder(old, new) == new and os.path.isdir(os.path.join(new, "wolvenkit"))
                  and not os.path.exists(old), "%LOCALAPPDATA% folder moved once")
            check(g.move_old_folder(old, new) == new, "second start: nothing to move")
            old, new = os.path.join(r, "Desktop", "TattooSwitcher"), os.path.join(r, "Desktop", "TattooSeparator")
            os.makedirs(os.path.join(old, "work", "mytat"))
            os.makedirs(new)
            for f in ("gui_settings.json", os.path.join("work", "mytat", "list.json")):
                with open(os.path.join(old, f), "w") as fh:
                    fh.write("{}")
            check(g.take_over_old_list(new) and os.path.isfile(os.path.join(new, "work", "mytat", "list.json"))
                  and os.path.isfile(os.path.join(new, "gui_settings.json"))
                  and os.path.isfile(os.path.join(old, "gui_settings.json")), "old exe folder's list copied over")
            check(not g.take_over_old_list(new), "copied only once")
        if closing:
            with open(os.path.join(a.base, "inputs.json"), encoding="utf-8") as f:
                a.t = json.load(f)
            if a.during == "download":
                ok = run_session(a, session_close_download)
                workers = getattr(a, "workers", [])
                for t in workers:
                    t.join(30)
                left = os.listdir(os.path.dirname(g.WK_HOME))
                log(
                    "window closed; download stopped: %s; left behind: %s"
                    % (bool(workers) and not any(t.is_alive() for t in workers), left)
                )
                ok = ok and left == []
            else:
                ok = run_session(a, session_close)
                log(
                    "window closed; WolvenKit still running: %d"
                    % sum(p.poll() is None for p in g.RUNNING)
                )
        else:
            if os.path.exists(g.SETTINGS):
                raise SystemExit("use an empty scratch dir")
            a.t = make_inputs(a)
            with open(os.path.join(a.base, "inputs.json"), "w", encoding="utf-8") as f:
                json.dump(a.t, f)
            ok = run_session(a, session1)
            if ok:  # restart with only Outfit Refitter's copy: our download moved there, setting forgotten
                os.makedirs(
                    os.path.dirname(os.path.dirname(g.REFITTER_WK[0])), exist_ok=True
                )
                shutil.move(g.WK_HOME, os.path.dirname(g.REFITTER_WK[0]))
                s = g.load_settings()
                del s["wolvenkit"]
                g.save_settings(s)
                with open(
                    os.path.join(g.USER, "work", "tgui1", "list.json"), encoding="utf-8"
                ) as f:
                    a.built = len(json.load(f)["tattoos"])
                ok = run_session(a, session2)
            for during in ("download", "build"):
                if not ok:
                    break
                log("== closing the window during the %s (separate process)" % during)
                cmd = [sys.executable] + (
                    []
                    if getattr(sys, "frozen", False)
                    else [os.path.abspath(g.__file__)]
                )
                cmd += ["--guitest-close", a.base, "--wk", a.wk, "--during", during]
                r = subprocess.run(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=900,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                out = r.stdout.decode("utf-8", "replace")
                with open(
                    os.path.join(a.base, "guitest_close.log"), encoding="utf-8"
                ) as f:
                    child = f.read()
                log("  child log:\n    " + child.strip().replace("\n", "\n    "))
                log("  child exit code %d, output %r" % (r.returncode, out))
                ok = r.returncode == 0 and not out.strip() and "FAIL" not in child
                ok = ok and "STDERR" not in child and "Traceback" not in child
                ok = ok and (
                    "still running: 0" in child
                    if during == "build"
                    else "download stopped: True; left behind: []" in child
                )
                if not ok:
                    FAILS.append(
                        "closing during the %s: exit %d %r"
                        % (during, r.returncode, out)
                    )
    except Exception:
        log("FAIL:\n" + traceback.format_exc())
        FAILS.append("crashed")
        ok = False
    if err.getvalue().strip():
        log("STDERR:\n" + err.getvalue())
        FAILS.append("something was printed to stderr")
        ok = False
    if not closing:
        log("\n== every message shown (%d):" % len(MSGS))
        for k, t, m in MSGS:
            log("  [%s] %s: %s" % (k, t, (m or "").replace("\n", " | ")))
    log(
        "GUITEST %s%s"
        % ("OK" if ok and not FAILS else "FAILED", "" if ok else ": %s" % FAILS)
    )
    LOG.close()
    return 0 if ok and not FAILS else 1
