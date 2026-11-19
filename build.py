"""Tattoo switchers for Cyberpunk 2077 character creation (ArchiveXL / CCXL).

Builds selectable body-tattoo rows ("Left Arm Tattoo: Off / Design A / Design B ...") from the
Fun Tattoos (Nexus 33230, by funsix) CCXL templates. Each design is a decal copy of the body/arm
mesh with its own texture, so tattoos are options instead of global overlay replacers.

usage: python build.py <template json dir> <out dir> [--config options.json]

  template json dir = WolvenKit-serialized Fun Tattoos files (see README, "Getting the templates"):
      arm_tattoo.app, arm_tattoo.mi, arm_tattoo_pwa.inkcharcustomization,
      fun_arm_tattoo_left_pwa.mesh, fun_arm_tattoo_right_pwa.mesh,
      chest_tattoo.app, your_chest_tattoo.mesh, your_chest_tattoo.morphtarget   (each as <name>.json)
  out dir = receives <depot path>.json for every generated file + the .archive.xl.
      Deserialize the jsons with WolvenKit, add your .xbm textures, pack. See README.

Rules this script enforces (each one fixed a real in-game bug):
  - HandleId/HandleRefId are renumbered file-wide after copying (copies past ~23 options collided).
  - Every copied app appearance gets its own compiledData BufferId (BufferIds are file-global too).
  - Component ids (CRUIDs) are derived from prefix + part, so they are stable across rebuilds.
  - One component name per part: options of a part replace each other, different parts stack.
  - Body decal: the component's morphResource points at our own copy of the morphtarget, re-pointed
    at our body mesh, so the tattoo follows the character-creator breast morph.
  - Decal material keeps only DiffuseTexture (mesh_decal.mt, no normal) and sets DiffuseAlpha.
  - Option order is append-only per part (saves store the switcher index). options.lock.json
    next to the config remembers the order and the build stops if you reorder or remove options.
"""

import argparse, copy, json, os, random, sys

# Template kinds. A part picks one; parts sharing a kind share its mesh/app but keep their own
# component, so they stack. To add a new kind (e.g. hands, legs from other Fun Tattoos files),
# serialize its mesh + app and add an entry here.
KINDS = {
    "arm_left": dict(
        mesh="fun_arm_tattoo_left_pwa.mesh",
        app="arm_tattoo.app",
        app_index=0,
        fun_mesh="funsix\\ccxl\\arm_tattoo\\meshes\\arm_tattoo\\fun_arm_tattoo_left_pwa.mesh",
    ),
    "arm_right": dict(
        mesh="fun_arm_tattoo_right_pwa.mesh",
        app="arm_tattoo.app",
        app_index=1,
        fun_mesh="funsix\\ccxl\\arm_tattoo\\meshes\\arm_tattoo\\fun_arm_tattoo_right_pwa.mesh",
    ),
    # Fun's chest decal = the whole body mesh (torso + legs share one UV); has a breast morphtarget
    "body": dict(
        mesh="your_chest_tattoo.mesh",
        app="chest_tattoo.app",
        app_index=0,
        morph="your_chest_tattoo.morphtarget",
    ),
}
MI_TEMPLATE = "arm_tattoo.mi"
CC_TEMPLATE = "arm_tattoo_pwa.inkcharcustomization"
# Fun's own CC entries used as templates: switcher, its Off option, one design option
CC_SWITCHER, CC_OFF, CC_OPTION = (
    "left_arm_tattoo",
    "left_arm_tattoo_off",
    "your_arm_tattoo_left",
)


def dp(p):  # accept / or \ in the config, game depot paths use \
    return p.replace("/", "\\")


def walk(o, fn):
    if isinstance(o, dict):
        fn(o)
        for v in o.values():
            walk(v, fn)
    elif isinstance(o, list):
        for v in o:
            walk(v, fn)


def replace_value(o, old, new):  # exact CName / ResourcePath string values
    def f(d):
        if d.get("$value") == old:
            d["$value"] = new

    walk(o, f)


def renumber(items):
    """HandleId/HandleRefId are file-global: renumber 0..n in document order after copying."""
    nxt = 0
    for it in items:
        m = {}

        def f(d):
            nonlocal nxt
            if "HandleId" in d:
                m[d["HandleId"]] = d["HandleId"] = str(nxt)
                nxt += 1

        walk(it, f)

        def g(d):
            if "HandleRefId" in d:
                d["HandleRefId"] = m[d["HandleRefId"]]

        walk(it, g)
    return items


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("templates")
    ap.add_argument("out")
    ap.add_argument(
        "--config",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "options.json"
        ),
    )
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))

    prefix = cfg["prefix"]
    root = dp(cfg["depot_root"]).rstrip("\\") + "\\"
    alpha = cfg.get(
        "diffuse_alpha", 1.0
    )  # Fun uses 0.6 (faded ink); 1.0 = full strength
    parts = {p["id"]: p for p in cfg["parts"]}
    opts = cfg[
        "options"
    ]  # order = switcher order: append only, never reorder/rename (saves)

    # --- validate config
    ids = [o["id"] for o in opts]
    assert len(set(ids)) == len(ids), "duplicate option id"
    for o in opts:
        assert o["part"] in parts, "option %s: unknown part %s" % (o["id"], o["part"])
        assert o["texture"].lower().endswith(".xbm"), (
            "option %s: texture must be an .xbm depot path" % o["id"]
        )
    for p in parts.values():
        assert p["kind"] in KINDS, "part %s: unknown kind %s (one of %s)" % (
            p["id"],
            p["kind"],
            list(KINDS),
        )
    check_order(a.config, parts, opts)

    def load(n):
        return json.load(open(os.path.join(a.templates, n + ".json"), encoding="utf-8"))

    written = []

    def save(d, rel):
        d["Header"]["ArchiveFileName"] = (
            rel  # template header holds the serializer's local path
        )
        p = os.path.join(a.out, *rel.split("\\")) + ".json"
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(d, open(p, "w", encoding="utf-8"), indent=1)
        written.append(rel)

    def names_of(kind=None, part=None):
        return [
            o["id"]
            for o in opts
            if (part is None or o["part"] == part)
            and (kind is None or parts[o["part"]]["kind"] == kind)
        ]

    tex = {o["id"]: dp(o["texture"]) for o in opts}
    label = {o["id"]: o["label"] for o in opts}
    MI = root + prefix + "_tattoo.mi"

    def comp_name(part):
        return "%s_%s_tattoo" % (prefix, part)

    def cruid(part):  # stable across rebuilds, distinct from Fun's ids
        return str(random.Random("%s_tattoo_%s" % (prefix, part)).getrandbits(63))

    # --- shared decal material instance (mesh_decal.mt)
    mi = load(MI_TEMPLATE)
    mi["Data"]["RootChunk"]["values"][0]["DiffuseAlpha"] = alpha
    save(mi, MI)

    app_of, app_names = {}, set()
    for kind, k in KINDS.items():
        names = names_of(kind=kind)
        if not names:
            continue
        mesh_path = root + "%s_tattoo_%s.mesh" % (prefix, kind)
        app_path = root + "%s_tattoo_%s.app" % (prefix, kind)
        morph_path = root + "%s_tattoo_%s.morphtarget" % (prefix, kind)

        # mesh: one appearance + one local material per option; every render chunk gets the material
        m = load(k["mesh"])
        rc = m["Data"]["RootChunk"]
        nchunks = len(rc["renderResourceBlob"]["Data"]["header"]["renderChunkInfos"])
        a0, e0, l0 = (
            rc["appearances"][0],
            rc["materialEntries"][0],
            rc["localMaterialBuffer"]["materials"][0],
        )
        (
            rc["appearances"],
            rc["materialEntries"],
            rc["localMaterialBuffer"]["materials"],
        ) = [], [], []
        for i, n in enumerate(names):
            app = copy.deepcopy(a0)
            app["HandleId"] = "a%d" % i  # unique before renumber (copies share the template's id)
            app["Data"]["name"]["$value"] = n
            app["Data"]["chunkMaterials"] = [
                {"$type": "CName", "$storage": "string", "$value": n}
            ] * nchunks
            e = copy.deepcopy(e0)
            e["index"], e["name"]["$value"] = i, n
            mat = copy.deepcopy(l0)
            mat["baseMaterial"]["DepotPath"]["$value"] = MI
            mat["values"] = [
                v for v in mat["values"] if "DiffuseTexture" in v
            ]  # decal: diffuse only
            mat["values"][0]["DiffuseTexture"]["DepotPath"]["$value"] = tex[n]
            rc["appearances"].append(app)
            rc["materialEntries"].append(e)
            rc["localMaterialBuffer"]["materials"].append(mat)
        renumber([rc])
        save(m, mesh_path)

        if (
            "morph" in k
        ):  # morphtarget re-pointed at our mesh (CC breast morph keeps working)
            mt = load(k["morph"])
            mrc = mt["Data"]["RootChunk"]
            mrc["baseMesh"]["DepotPath"]["$value"] = mesh_path
            mrc["baseMeshAppearance"]["$value"] = names[0]
            save(mt, morph_path)

        # app: one appearance per option; component named per part -> a part's options replace each other
        appf = load(k["app"])
        arc = appf["Data"]["RootChunk"]
        tpl = arc["appearances"][k["app_index"]]
        out = []
        for n in names:
            part = next(o["part"] for o in opts if o["id"] == n)
            app = copy.deepcopy(tpl)
            t = app["Data"]
            t["name"]["$value"] = "w__" + n
            if "fun_mesh" in k:
                replace_value(app, k["fun_mesh"], mesh_path)
            for c in t["components"] + t["compiledData"]["Data"]["Chunks"]:
                c["meshAppearance"]["$value"] = n
                c["name"]["$value"] = comp_name(part)
                c["id"] = cruid(part)
                if "morph" in k:
                    c["morphResource"]["DepotPath"] = {
                        "$type": "ResourcePath",
                        "$storage": "string",
                        "$value": morph_path,
                    }
            t["compiledData"]["Data"]["CruidDict"] = {"0": cruid(part)}
            out.append(app)
        for i, app in enumerate(out):
            app["Data"]["compiledData"]["BufferId"] = str(
                i
            )  # BufferIds are file-global
        arc["appearances"] = renumber(out)
        save(appf, app_path)
        app_names |= {x["Data"]["name"]["$value"] for x in out}
        for n in names:
            app_of[n] = app_path

    # --- inkcharcustomization: per part a switcher row + Off + one body option per design
    cc = load(CC_TEMPLATE)
    rc = cc["Data"]["RootChunk"]
    src = {o["Data"]["name"]["$value"]: o for o in rc["bodyCustomizationOptions"]}
    out = []
    for pid, p in parts.items():
        designs = names_of(part=pid)
        if not designs:
            print("note: part %s has no options, skipped" % pid)
            continue
        swname = comp_name(pid)
        off = swname + "_off"
        sw = copy.deepcopy(src[CC_SWITCHER])
        d = sw["Data"]
        d["name"]["$value"], d["localizedName"], d["index"], d["defaultIndex"] = (
            swname,
            p["label"],
            p["ui_index"],
            0,
        )
        d["uiSlot"]["$value"] = (
            swname + "_switcher"
        )  # the row's uiSlot (salon/studio filters key on this)
        d["uiSlots"][0]["$value"] = swname
        opt0 = d["options"][0]
        d["options"] = []
        for i, n in enumerate([off] + designs):
            o = copy.deepcopy(opt0)
            o["index"] = i
            o["names"][0]["$value"] = n
            o["localizedName"] = "Common-Off" if i == 0 else label[n]
            d["options"].append(o)
        out.append(sw)
        o = copy.deepcopy(src[CC_OFF])
        o["Data"]["name"]["$value"] = off
        o["Data"]["uiSlot"]["$value"] = swname
        out.append(o)
        for n in designs:
            o = copy.deepcopy(src[CC_OPTION])
            od = o["Data"]
            od["name"]["$value"] = n
            od["uiSlot"]["$value"] = swname
            od["resource"]["DepotPath"]["$value"] = app_of[n]
            od["definitions"][0]["name"]["$value"] = "w__" + n
            out.append(o)
    rc["bodyCustomizationOptions"] = renumber(out)
    allnames = [o["Data"]["name"]["$value"] for o in out]
    for g in rc["bodyGroups"]:
        g["options"] = [
            {"$type": "CName", "$storage": "string", "$value": n} for n in allnames
        ]
    cc_path = root + prefix + "_tattoos_pwa.inkcharcustomization"
    save(cc, cc_path)

    xl = os.path.join(a.out, prefix + "_tattoos.archive.xl")
    with open(xl, "w", encoding="utf-8") as f:
        f.write("customizations:\n  female: %s\n" % cc_path)

    # --- self-checks: switcher options exist, every option has its app appearance, names unique
    for o in out:
        if o["Data"]["$type"] == "gameuiSwitcherInfo":
            for so in o["Data"]["options"]:
                assert so["names"][0]["$value"] in allnames
    assert app_names == {"w__" + n for n in ids}, "app appearances do not match options"
    assert len(set(allnames)) == len(allnames), (
        "duplicate CC option names (an option id clashes with a switcher/off name?)"
    )
    write_lock(a.config, parts, opts)

    print(
        "ok: %d options in %d rows"
        % (len(opts), sum(1 for o in out if o["Data"]["$type"] == "gameuiSwitcherInfo"))
    )
    print("wrote:", *written, os.path.basename(xl), sep="\n  ")
    print(
        "textures to add (as .xbm at these depot paths):",
        *sorted(set(tex.values())),
        sep="\n  ",
    )


def lock_path(config):
    return os.path.join(os.path.dirname(os.path.abspath(config)), "options.lock.json")


def order(parts, opts):
    return {p: [o["id"] for o in opts if o["part"] == p] for p in parts}


def check_order(config, parts, opts):
    """Saves keep the switcher index: old options must stay in place, new ones go at the end."""
    try:
        old = json.load(open(lock_path(config), encoding="utf-8"))
    except FileNotFoundError:
        return
    new = order(parts, opts)
    for p, ids in old.items():
        if new.get(p, [])[: len(ids)] != ids:
            sys.exit(
                "option order changed for part %r (append only, or existing saves pick the wrong tattoo).\n"
                "  was: %s\n  now: %s\nDelete %s if you accept that."
                % (p, ids, new.get(p), lock_path(config))
            )


def write_lock(config, parts, opts):
    json.dump(
        order(parts, opts), open(lock_path(config), "w", encoding="utf-8"), indent=1
    )


if __name__ == "__main__":
    main()
