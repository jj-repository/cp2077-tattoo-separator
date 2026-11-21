"""Drives the real Tattoo Switchers window like a user would: every button, through the widgets.

  python tattoo_switcher_gui.py --guitest <empty scratch dir> --fun <Fun Tattoos Angel .archive>
      --mod <tattoo mod .archive with arm + v_overlay textures> --xbm <arm .xbm> --png <arm .png>
      [--wk <WolvenKit.CLI.exe>] [--nomatch <.archive without tattoo textures>]
  (TattooSwitcher.exe --guitest ... works the same.)

Only file pickers and message boxes are replaced (they return prepared answers; every message text is
logged for review). Everything else is the real window: buttons are found by their text and invoke()d,
dialogs are filled in through their widgets, builds are awaited through the window's own busy state.
Installs go into a fake game folder inside the scratch dir. Writes <scratch>/guitest.log, exits 0 / 1.
"""

import argparse, io, json, os, shutil, subprocess, sys, time, traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

g = sys.modules["__main__"]  # tattoo_switcher_gui (started through its main())
assert hasattr(g, "run_gui"), "start this through tattoo_switcher_gui.py --guitest"

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


# ----------------------------------------------------------------------------- the user session
def session1(a, d):
    app = d.app
    T = a.t
    log("== first start")
    check(app.wk_var.get().startswith("not set"), "WolvenKit shows 'not set'")
    check(app.tpl_var.get().startswith("not set"), "templates show 'not set'")
    check(
        app.prefix_var.get() == "mytat" and rows(app) == [],
        "default mod 'mytat', empty list",
    )

    log("== unexpected error in a callback -> log box + plain message")
    n = len(MSGS)
    d.root.after(0, lambda: 1 / 0)
    yield d.pause(300)
    expect(n, "error", "Something unexpected went wrong")
    check("ZeroDivisionError" in logtext(app), "traceback is in the log box")
    a.expected_tracebacks += 1

    log("== missing WolvenKit")
    n = len(MSGS)
    yield d.click("Build mod")
    expect(n, "error", "WolvenKit is not set up yet")
    n = len(MSGS)
    FILES.append(a.fun)
    yield d.click("Get templates...")
    expect(n, "error", "WolvenKit is not set up yet")

    log("== Find WolvenKit")
    n = len(MSGS)
    FILES.append(sys.executable)
    yield d.click("Find WolvenKit...")
    expect(n, "error", "Please pick WolvenKit.CLI.exe")
    n = len(MSGS)
    FILES.append("")  # cancel
    yield d.click("Find WolvenKit...")
    no_msgs(n, "cancelled picker")
    FILES.append(a.wk.replace("\\", "/"))  # Tk pickers return forward slashes
    yield d.click("Find WolvenKit...")
    check(app.wk_var.get() == os.path.normpath(a.wk), "WolvenKit path shown")

    log("== Get templates: wrong inputs, then the real archive")
    n = len(MSGS)
    FILES.append(T["txt"])
    yield d.click("Get templates...")
    yield d.idle()
    expect(n, "error", "Please pick the Fun Tattoos .archive file")
    n = len(MSGS)
    FILES.append(T["mod"])
    yield d.click("Get templates...")
    yield d.idle()
    expect(n, "error", "doesn't look like the Fun Tattoos archive")
    n = len(MSGS)
    FILES.append(T["fakearchive"])
    yield d.click("Get templates...")
    yield d.idle()
    expect(n, "error", "WolvenKit could not")
    n = len(MSGS)
    FILES.append(a.fun)
    yield d.click("Get templates...")
    check(app.build_btn.instate(["disabled"]), "buttons disabled while a step runs")
    yield d.idle(600)
    no_msgs(n, "templates from the real archive")
    check(app.tpl_var.get() == "ready", "templates ready")

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
    yield d.dialog("Tattoo Switchers - Help")
    h = d.dialogs("Tattoo Switchers - Help")[0]
    text = d.find(tk.Text, top=h)[0].get("1.0", "end")
    for s in (
        "Steps, in order",
        "33230",
        "Fun Tattoos Angel Body",
        "only for a female V with the Angel body",
        "red line",
        "add, never remove",
    ):
        check(s.lower() in text.lower(), "help mentions %r" % s)
    yield d.click("Close", h)
    yield d.gone("Tattoo Switchers - Help")

    log("== Install / Open folder before building")
    n = len(MSGS)
    yield d.click("Install to game...")
    expect(n, "info", "Build the mod first")
    yield d.click("Open folder")
    check(OPENED and OPENED[-1] == app.out, "Open folder opens the output folder")

    log("== Build (with the one-time game-file step)")
    real_oodle, g.OODLE = (
        g.OODLE,
        os.path.join(a.base, "oodle test", "oo2ext_7_win64.dll"),
    )
    os.makedirs(os.path.dirname(g.OODLE), exist_ok=True)
    try:
        n = len(MSGS)
        ANSWERS.append(False)
        yield d.click("Build mod")
        expect(n, "askokcancel", "oo2ext_7_win64.dll")
        check(not app.busy, "cancel: no build")
        n = len(MSGS)
        FILES.append(a.base)
        yield d.click("Build mod")
        expect(n, "error", "doesn't look like the Cyberpunk 2077 folder")
        check(not app.busy, "wrong folder: no build")
        FILES.append(T["game"])
        yield d.click("Build mod")
        check(os.path.isfile(g.OODLE), "game file copied (to the test location)")
    finally:
        g.OODLE = real_oodle
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
    expect(n, "info", "remove the tattoo mods")
    mod = os.path.join(T["game"], "archive", "pc", "mod")
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
    listing = g.WolvenKit(a.wk, lambda m: None).listing(archive)
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
    check(
        app.tpl_var.get() == "ready" and app.wk_var.get() == os.path.normpath(a.wk),
        "setup remembered",
    )
    check(app.alpha_lbl.cget("text") == "0.80", "ink remembered")
    log("== Install right after a restart (no rebuild)")
    n = len(MSGS)
    FILES.append(a.t["game"])
    yield d.click("Install to game...")
    expect(n, "info", "Copied both files")
    log("== WolvenKit gone missing")
    app.s["wolvenkit"] = os.path.join(a.base, "gone", "WolvenKit.CLI.exe")
    n = len(MSGS)
    yield d.click("Build mod")
    expect(n, "error", "WolvenKit is not set up yet")
    app.s["wolvenkit"] = os.path.normpath(a.wk)
    check("Traceback" not in logtext(app), "no tracebacks in the log box")
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
    patch_dialogs()
    a.expected_tracebacks = 0
    ok = True
    try:
        if closing:
            with open(os.path.join(a.base, "inputs.json"), encoding="utf-8") as f:
                a.t = json.load(f)
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
            if ok:
                with open(
                    os.path.join(g.USER, "work", "tgui1", "list.json"), encoding="utf-8"
                ) as f:
                    a.built = len(json.load(f)["tattoos"])
                ok = run_session(a, session2)
            if ok:
                log("== closing the window during a build (separate process)")
                cmd = [sys.executable] + (
                    []
                    if getattr(sys, "frozen", False)
                    else [os.path.abspath(g.__file__)]
                )
                cmd += ["--guitest-close", a.base, "--wk", a.wk]
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
                ok = ok and "STDERR" not in child and "still running: 0" in child
                if not ok:
                    FAILS.append(
                        "closing during a build: exit %d %r" % (r.returncode, out)
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
