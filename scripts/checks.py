"""Consistency checks on the extracted overlay data.

All functions are pure: they take the dicts written by build.py (data/*.json) plus NIST's
OSCAL content, and return lists of findings. build.py turns findings into reports/consistency.md.
"""

import json

LEVELS = ("LOW", "MOD", "HIGH")
NIST_LEVEL = {"LOW": "LOW", "MOD": "MODERATE", "HIGH": "HIGH"}


def catalog_index(catalog_path):
    """{oscal_id: {"label": "AC-2(1)", "status": "withdrawn" or ""}} for every control in the catalog."""
    cat = json.load(open(catalog_path))["catalog"]
    idx = {}

    def walk(controls):
        for c in controls:
            props = c.get("props", [])
            lbl = next(
                (p["value"] for p in props if p["name"] == "label" and p.get("class") != "zero-padded"),
                None,
            )
            status = next((p["value"] for p in props if p["name"] == "status"), "")
            idx[c["id"]] = {"label": lbl, "status": status, "title": c.get("title", "")}
            walk(c.get("controls", []))

    for g in cat["groups"]:
        walk(g.get("controls", []))
    return idx


def baseline_ids(profile_path):
    prof = json.load(open(profile_path))["profile"]
    ids = set()
    for imp in prof["imports"]:
        for inc in imp.get("include-controls", []):
            ids.update(inc.get("with-ids", []))
    return ids


def check_ids(rows, cat_idx, to_oscal):
    """Every row label must resolve to a non-withdrawn control in the catalog. Returns problems."""
    problems = []
    for lbl in sorted(rows):
        try:
            oid = to_oscal(lbl)
        except ValueError as e:
            problems.append(f"{lbl}: {e}")
            continue
        if oid not in cat_idx:
            problems.append(f"{lbl}: no control '{oid}' in the SP 800-53r5 catalog")
        elif cat_idx[oid]["status"] == "withdrawn":
            problems.append(f"{lbl}: control '{oid}' is withdrawn in SP 800-53r5")
        elif cat_idx[oid]["label"] != lbl:
            problems.append(f"{lbl}: catalog label for '{oid}' is {cat_idx[oid]['label']}")
    return problems


def marked(detailed, lv, kinds):
    return {k for k, v in detailed.items() if v["markers"].get(lv) in kinds}


def summary_vs_detailed(summary, detailed):
    """Per level, IDs printed in the summary table versus IDs with a marker in the detailed tables.

    A struck-through (removed) ID still prints in the summary, so Remove counts as present.
    """
    out = []
    for lv in LEVELS:
        # PM controls are organization-wide and printed once across all three columns
        s = {k for k in summary[lv] if not k.startswith("PM-")}
        d = marked(detailed, lv, {"Select", "Add", "Remove"})
        for k in sorted(s - d, key=sort_key):
            out.append({"level": lv, "label": k, "kind": "summary-only",
                        "summary_pages": summary[lv][k],
                        "detailed_markers": detailed.get(k, {}).get("markers"),
                        "detailed_page": detailed.get(k, {}).get("page")})
        for k in sorted(d - s, key=sort_key):
            out.append({"level": lv, "label": k, "kind": "detailed-only",
                        "detailed_markers": detailed[k]["markers"], "detailed_page": detailed[k]["page"]})
    return out


def detailed_vs_53b(detailed, base, privacy, to_oscal):
    """Compare Select markers with the SP 800-53B baselines.

    base: level -> set of OSCAL ids in NIST's 53B baseline profile.
    privacy: set of OSCAL ids in the 53B privacy baseline (the overlay drops privacy-only controls).
    """
    out = []
    for lv in LEVELS:
        sel = {to_oscal(k) for k in marked(detailed, lv, {"Select"})}
        add = {to_oscal(k) for k in marked(detailed, lv, {"Add"})}
        rem = {to_oscal(k) for k in marked(detailed, lv, {"Remove"})}
        b = base[lv]
        for i in sorted(sel - b):
            out.append({"level": lv, "id": i, "kind": "select-not-in-53B"})
        for i in sorted(add & b):
            out.append({"level": lv, "id": i, "kind": "add-already-in-53B"})
        for i in sorted(rem - b):
            out.append({"level": lv, "id": i, "kind": "remove-not-in-53B"})
        missing = b - sel - rem
        for i in sorted(missing):
            out.append({"level": lv, "id": i,
                        "kind": "53B-control-unmarked-privacy" if i in privacy else "53B-control-unmarked"})
    return out


def edition_diff(old, new):
    """Marker changes between two editions' detailed tables."""
    out = []
    for k in sorted(set(old) | set(new), key=sort_key):
        a = old.get(k, {}).get("markers")
        b = new.get(k, {}).get("markers")
        if a is None:
            out.append({"label": k, "kind": "row-added", "new": b})
        elif b is None:
            out.append({"label": k, "kind": "row-removed", "old": a})
        elif a != b:
            out.append({"label": k, "kind": "markers-changed", "old": a, "new": b})
    return out


def sort_key(lbl):
    fam, rest = lbl.split("-", 1)
    num, _, enh = rest.partition("(")
    return (fam, int(num), int(enh.rstrip(")") or 0))
