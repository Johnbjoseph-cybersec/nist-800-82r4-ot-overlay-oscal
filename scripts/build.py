"""Build the OSCAL rendering of the SP 800-82r4 ipd OT overlay, and the consistency report.

    python3 scripts/build.py            # regenerate data/, overlay/ and reports/
    python3 scripts/build.py --check    # regenerate in memory and fail if any committed file differs

Inputs (see SOURCES.md): sources/*.pdf (fetched by scripts/fetch_sources.sh, hash-checked here)
and vendor/nist-oscal-content/ (NIST's SP 800-53r5 catalog and SP 800-53B baseline profiles).
Output is deterministic: no timestamps or random UUIDs, so --check can compare byte for byte.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import checks  # noqa: E402
import overlay as ov  # noqa: E402

VENDOR = ROOT / "vendor" / "nist-oscal-content"
CATALOG = VENDOR / "NIST_SP-800-53_rev5_catalog.json"
NS = "urn:uuid:5c1f1a0e-82a4-4d0e-9b8a-0f8a2d0c8204"  # namespace for the overlay's own props/parts
UUID_NS = uuid.UUID("5c1f1a0e-82a4-4d0e-9b8a-0f8a2d0c8204")
VERSION = "0.1.0"
STAMP = "2026-11-12T00:00:00Z"  # fixed so the build is reproducible; bump with VERSION
OSCAL_VERSION = "1.2.3"  # matches the vendored NIST catalog
PDF_URL = {
    "r4-ipd": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-82r4.ipd.pdf",
    "r3": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-82r3.pdf",
}
LEVEL_FILE = {"LOW": "LOW", "MOD": "MODERATE", "HIGH": "HIGH"}
PAGE_OFFSET_R4 = 18  # printed page = PDF page - 18 in the r4 ipd (PDF p. 224 is printed p. 206)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def uid(*parts):
    return str(uuid.uuid5(UUID_NS, "/".join(parts)))


def dump(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def require_source(ed):
    pdf = ROOT / "sources" / ed.pdf_name
    if not pdf.exists():
        sys.exit(f"missing {pdf}: run scripts/fetch_sources.sh")
    got = sha256(pdf)
    if got != ed.sha256:
        sys.exit(f"{pdf} has SHA-256 {got}, expected {ed.sha256}")
    return pdf


# ---------------------------------------------------------------- extraction


def extract():
    pdf4, pdf3 = require_source(ov.R4), require_source(ov.R3)
    r4 = ov.read_tables(pdf4, ov.R4)
    r3 = ov.read_tables(pdf3, ov.R3)
    d0, d1 = r4.pages["detailed"]
    families, prose, anomalies, subsections = ov.read_prose(pdf4, ov.R4, d0, d1, r4.tables)
    bold = ov.read_summary_bold(pdf4, r4.summary_pos)
    return pdf4, r4, r3, families, prose, anomalies, subsections, bold


def build_data(r4, r3, families, prose, anomalies, subsections, bold, idx):
    controls = {}
    for lbl in sorted(set(r4.detailed) | set(prose), key=checks.sort_key):
        oid = ov.oscal_id(lbl)
        row = r4.detailed.get(lbl)
        p = prose.get(lbl, {})
        controls[lbl] = {
            "oscal_id": oid,
            "title": idx[oid]["title"] if oid in idx else None,
            "markers": row["markers"] if row else None,
            "table_pdf_page": row["page"] if row else None,
            "ot_discussion": p.get("discussion"),
            "ot_discussion_line": p.get("discussion_line"),
            "no_ot_discussion_line": p.get("no_ot_discussion_line"),
            "rationale": p.get("rationale", []),
        }
    data_r4 = {
        "source": {
            "document": "NIST SP 800-82 Rev. 4 initial public draft (ipd), Guide to Operational Technology (OT) Security, 21 September 2026",
            "url": PDF_URL["r4-ipd"],
            "sha256": ov.R4.sha256,
            "appendix": "Appendix E. OT Overlay",
            "pdf_pages": {"summary_table": r4.pages["summary"], "detailed_tables": r4.pages["detailed"]},
            "line_numbers": "ot_discussion_line and similar fields are the draft's own line numbers",
        },
        "families": families,
        "subsection_headings": subsections,
        "controls": controls,
        "summary_table": {lv: sorted(r4.summary[lv], key=checks.sort_key) for lv in ov.LEVELS},
        "summary_table_bold": {lv: {k: bold[lv][k] for k in sorted(bold[lv], key=checks.sort_key)} for lv in ov.LEVELS},
        "text_anomalies": anomalies,
    }
    data_r3 = {
        "source": {
            "document": "NIST SP 800-82 Rev. 3 (final), Guide to Operational Technology (OT) Security, September 2023",
            "url": PDF_URL["r3"],
            "sha256": ov.R3.sha256,
            "appendix": "Appendix F. OT Overlay",
            "pdf_pages": {"summary_table": r3.pages["summary"], "detailed_tables": r3.pages["detailed"]},
            "errata_applied": [
                {"pdf_page": p, "printed": a, "read_as": b, "evidence": why} for p, a, b, why in ov.R3.errata
            ],
        },
        "controls": {
            k: {"markers": v["markers"], "table_pdf_page": v["page"]}
            for k, v in sorted(r3.detailed.items(), key=lambda kv: checks.sort_key(kv[0]))
        },
        "summary_table": {lv: sorted(r3.summary[lv], key=checks.sort_key) for lv in ov.LEVELS},
    }
    return data_r4, data_r3


# ---------------------------------------------------------------- OSCAL


def profile(level, data_r4, catalog_sha):
    controls = data_r4["controls"]
    lv = level
    included = [k for k, c in controls.items() if c["markers"] and c["markers"].get(lv) in ("Select", "Add")]
    removed = [k for k, c in controls.items() if c["markers"] and c["markers"].get(lv) == "Remove"]
    cat_res = uid("resource", "sp800-53r5-catalog")
    src_res = uid("resource", "sp800-82r4-ipd")
    alters = []
    for k in included:
        c = controls[k]
        add = {"position": "ending"}
        props = []
        if c["markers"][lv] == "Add":
            props.append({"name": "ot-overlay-action", "ns": NS, "value": "added",
                          "remarks": f"Added to the {LEVEL_FILE[lv]} baseline by the SP 800-82r4 ipd OT overlay."})
        parts = []
        if c["ot_discussion"]:
            parts.append({
                "id": f"{c['oscal_id']}_ot-discussion",
                "name": "ot-discussion",
                "ns": NS,
                "title": "OT Discussion",
                "props": [{"name": "source-line", "ns": NS, "value": str(c["ot_discussion_line"])}],
                "prose": c["ot_discussion"],
            })
        for i, r in enumerate(c["rationale"]):
            if r["action"] != "adding":
                continue
            parts.append({
                "id": f"{c['oscal_id']}_ot-rationale-{i + 1}",
                "name": "ot-rationale",
                "ns": NS,
                "title": f"Rationale for adding to {r['baselines']}",
                "props": [{"name": "source-line", "ns": NS, "value": str(r["line"])}],
                "prose": r["text"],
            })
        if props:
            add["props"] = props
        if parts:
            add["parts"] = parts
        if props or parts:
            alters.append({"control-id": c["oscal_id"], "adds": [add]})
    meta_props = [
        {"name": "source-sha256", "ns": NS, "value": data_r4["source"]["sha256"]},
        {"name": "baseline", "ns": NS, "value": LEVEL_FILE[lv]},
    ]
    for k in removed:
        c = controls[k]
        why = " ".join(r["text"] for r in c["rationale"] if r["action"] == "removing")
        meta_props.append({"name": "ot-overlay-removed", "ns": NS, "value": c["oscal_id"],
                           "remarks": f"Removed from the {LEVEL_FILE[lv]} baseline by the OT overlay. Rationale (draft): {why}"})
    return {
        "profile": {
            "uuid": uid("profile", lv),
            "metadata": {
                "title": f"NIST SP 800-82r4 ipd OT Overlay: {LEVEL_FILE[lv]} baseline (unofficial machine-readable rendering of a draft)",
                "last-modified": STAMP,
                "version": VERSION,
                "oscal-version": OSCAL_VERSION,
                "props": meta_props,
                "remarks": (
                    "Unofficial. Generated by script from the initial public draft of NIST SP 800-82 Rev. 4 "
                    "(Appendix E), which is subject to change. Not produced, reviewed or endorsed by NIST. "
                    "Controls: the SP 800-53B baseline as tailored by the overlay (Select or Add markers). "
                    "OT Discussion and rationale text is quoted from the draft."
                ),
            },
            "imports": [{"href": f"#{cat_res}", "include-controls": [{"with-ids": [controls[k]["oscal_id"] for k in included]}]}],
            "merge": {"as-is": True},
            "modify": {"alters": alters},
            "back-matter": {
                "resources": [
                    {
                        "uuid": cat_res,
                        "title": "NIST SP 800-53 Rev. 5 catalog (OSCAL), vendored from usnistgov/oscal-content",
                        "rlinks": [{
                            "href": "../vendor/nist-oscal-content/NIST_SP-800-53_rev5_catalog.json",
                            "media-type": "application/oscal.catalog+json",
                            "hashes": [{"algorithm": "SHA-256", "value": catalog_sha}],
                        }],
                    },
                    {
                        "uuid": src_res,
                        "title": "NIST SP 800-82 Rev. 4 initial public draft (source of the overlay)",
                        "rlinks": [{
                            "href": PDF_URL["r4-ipd"],
                            "media-type": "application/pdf",
                            "hashes": [{"algorithm": "SHA-256", "value": data_r4["source"]["sha256"]}],
                        }],
                    },
                ]
            },
        }
    }


def verify_profile(prof, idx):
    """Every control id a profile names must exist, un-withdrawn, in the SP 800-53r5 catalog."""
    p = prof["profile"]
    names = [i for imp in p["imports"] for inc in imp.get("include-controls", []) for i in inc["with-ids"]]
    names += [a["control-id"] for a in p.get("modify", {}).get("alters", [])]
    names += [pr["value"] for pr in p["metadata"].get("props", []) if pr["name"] == "ot-overlay-removed"]
    bad = [n for n in names if n not in idx or idx[n]["status"] == "withdrawn"]
    included = {i for imp in p["imports"] for inc in imp.get("include-controls", []) for i in inc["with-ids"]}
    orphan = [a["control-id"] for a in p.get("modify", {}).get("alters", []) if a["control-id"] not in included]
    return [f"unknown or withdrawn control id: {n}" for n in bad] + [f"alter targets a control not included: {n}" for n in orphan]


# ---------------------------------------------------------------- checks and report


def run_checks(r4, r3, data_r4, idx):
    base = {lv: checks.baseline_ids(VENDOR / f"NIST_SP-800-53_rev5_{LEVEL_FILE[lv]}-baseline_profile.json") for lv in ov.LEVELS}
    privacy = checks.baseline_ids(VENDOR / "NIST_SP-800-53_rev5_PRIVACY-baseline_profile.json")
    controls = data_r4["controls"]
    bold = data_r4["summary_table_bold"]
    labels = set().union(*[bold[lv] for lv in ov.LEVELS])
    bold_any = {k: any(bold[lv].get(k) for lv in ov.LEVELS) for k in labels}
    has_disc = {k: bool(controls.get(k, {}).get("ot_discussion")) for k in labels}
    out = {
        "id_problems_r4": checks.check_ids(r4.detailed, idx, ov.oscal_id)
        + checks.check_ids({k for lv in r4.summary for k in r4.summary[lv]}, idx, ov.oscal_id),
        "id_problems_r3": checks.check_ids(r3.detailed, idx, ov.oscal_id),
        "r4_summary_vs_detailed": checks.summary_vs_detailed(r4.summary, r4.detailed),
        "r3_summary_vs_detailed": checks.summary_vs_detailed(r3.summary, r3.detailed),
        "r4_detailed_vs_53B": checks.detailed_vs_53b(r4.detailed, base, privacy, ov.oscal_id),
        "r3_to_r4_marker_changes": checks.edition_diff(r3.detailed, r4.detailed),
        "bold_differs_across_columns": sorted(
            {k for lv in ov.LEVELS for k, b in bold[lv].items() for l2 in ov.LEVELS if k in bold[l2] and bold[l2][k] != b},
            key=checks.sort_key),
        "bold_without_discussion": sorted((k for k in labels if bold_any[k] and not has_disc[k]), key=checks.sort_key),
        "discussion_without_bold": sorted((k for k in labels if has_disc[k] and not bold_any[k]), key=checks.sort_key),
        "rationale_vs_add_remove": sorted(
            set(k for k, c in controls.items() if c["rationale"])
            ^ set(k for k, c in controls.items() if c["markers"] and set(c["markers"].values()) & {"Add", "Remove"}),
            key=checks.sort_key),
        "title_mismatches": title_mismatches(r4, data_r4, idx),
        "subsection_numbering": [s for s in data_r4["subsection_headings"] if s["ordinal"] != 1],
        "counts": {
            lv: {
                "sp800_53b": len(base[lv]),
                "select": len(checks.marked(r4.detailed, lv, {"Select"})),
                "add": len(checks.marked(r4.detailed, lv, {"Add"})),
                "remove": len(checks.marked(r4.detailed, lv, {"Remove"})),
                "overlay": len(checks.marked(r4.detailed, lv, {"Select", "Add"})),
            }
            for lv in ov.LEVELS
        },
    }
    return out


def title_mismatches(r4, data_r4, idx):
    """Control titles printed in the draft that differ from the SP 800-53r5 catalog title."""
    norm = lambda t: re.sub(r"[^A-Z0-9]", "", t.upper())  # noqa: E731
    out = []
    for lbl, row in r4.detailed.items():
        if "(" in lbl or not row["name"]:
            continue  # enhancement names and wrapped names are not compared
        t = idx[ov.oscal_id(lbl)]["title"]
        if norm(row["name"]) != norm(t):
            out.append({"label": lbl, "where": f"detailed table, PDF p. {row['page']}", "printed": row["name"], "sp800_53r5": t})
    return sorted(out, key=lambda x: checks.sort_key(x["label"]))


def report_md(res, data_r4, data_r3, anomalies):
    L = []
    w = L.append
    w("# Consistency report: SP 800-82r4 ipd OT overlay\n")
    w("Generated by `scripts/build.py`. Every check below runs on every build; the tests in")
    w("`tests/` prove each detector fires on a deliberately broken fixture, so a zero here is a")
    w("measured zero, not an unrun check.\n")
    w(f"- r4 ipd SHA-256 `{data_r4['source']['sha256']}`")
    w(f"- r3 SHA-256 `{data_r3['source']['sha256']}`\n")
    w("## Counts per baseline (detailed tables)\n")
    w("| Baseline | SP 800-53B | Select | Add | Remove | Overlay (Select + Add) | 53B - Remove + Add |")
    w("|---|---|---|---|---|---|---|")
    for lv, c in res["counts"].items():
        w(f"| {LEVEL_FILE[lv]} | {c['sp800_53b']} | {c['select']} | {c['add']} | {c['remove']} | {c['overlay']} | {c['sp800_53b'] - c['remove'] + c['add']} |")
    w("")

    def section(title, key, explain):
        items = res[key]
        w(f"## {title}: {len(items)} finding(s)\n")
        w(explain + "\n")
        for it in items:
            w(f"- `{json.dumps(it, ensure_ascii=False)}`")
        w("")

    section("Control IDs not in the SP 800-53r5 catalog (r4)", "id_problems_r4", "Every ID in the summary and detailed tables, looked up in NIST's OSCAL catalog.")
    section("Control IDs not in the SP 800-53r5 catalog (r3)", "id_problems_r3", "Same check for r3.")
    section("Summary table vs detailed tables (r4)", "r4_summary_vs_detailed", "Per baseline, IDs printed in Table 18 against IDs with a Select, Add or Remove marker in E.7. Struck-through IDs still print in Table 18, so Remove counts as present. PM is printed once across all columns and is excluded.")
    section("Summary table vs detailed tables (r3)", "r3_summary_vs_detailed", "Same check for r3 Table 22 and F.7.")
    section("Detailed tables vs SP 800-53B (r4)", "r4_detailed_vs_53B", "Select must be in the 53B baseline; Add must not be; Remove must be; every 53B control must carry Select or Remove.")
    section("Marker changes from r3 to r4", "r3_to_r4_marker_changes", "Per control and baseline, the r3 marker against the r4 ipd marker. Rows present in only one edition are listed too.")
    section("Table 18 bold differs between columns", "bold_differs_across_columns", "Table 18's key: bold marks controls with an OT discussion.")
    section("Bold in Table 18 but no OT discussion in E.7", "bold_without_discussion", "")
    section("OT discussion in E.7 but not bold in Table 18", "discussion_without_bold", "")
    section("Rationale present vs Add/Remove marker", "rationale_vs_add_remove", "Every Add or Remove should carry a rationale and vice versa.")
    section("Titles differing from SP 800-53r5", "title_mismatches", "Base-control names in the detailed tables, compared with the catalog title (case and punctuation ignored).")
    section("Third-level subsection numbers that do not restart at 1", "subsection_numbering", "Family subsections (Tailoring Considerations, Characteristics) under E.7.n.")
    w(f"## Text anomalies recorded by the parser: {len(anomalies)}\n")
    w("Lines the parser accepted but that depart from the draft's stated format. Not all are comment-worthy.\n")
    for a in anomalies:
        w(f"- line {a['line']} (PDF p. {a['page']}): {a['kind']}: \"{a['text']}\"")
    w("")
    return "\n".join(L)


# ---------------------------------------------------------------- main


def outputs():
    idx = checks.catalog_index(CATALOG)
    pdf4, r4, r3, families, prose, anomalies, subsections, bold = extract()
    problems = checks.check_ids(r4.detailed, idx, ov.oscal_id) + checks.check_ids(r3.detailed, idx, ov.oscal_id)
    if problems:
        sys.exit("control IDs not in the SP 800-53r5 catalog:\n  " + "\n  ".join(problems))
    data_r4, data_r3 = build_data(r4, r3, families, prose, anomalies, subsections, bold, idx)
    files = {
        "data/overlay-r4-ipd.json": dump(data_r4),
        "data/overlay-r3.json": dump(data_r3),
    }
    cat_sha = sha256(CATALOG)
    for lv in ov.LEVELS:
        prof = profile(lv, data_r4, cat_sha)
        bad = verify_profile(prof, idx)
        if bad:
            sys.exit(f"{lv} profile failed verification:\n  " + "\n  ".join(bad))
        files[f"overlay/NIST_SP-800-82r4-ipd_OT-overlay_{LEVEL_FILE[lv]}_profile.json"] = dump(prof)
    res = run_checks(r4, r3, data_r4, idx)
    files["reports/consistency.json"] = dump(res)
    files["reports/consistency.md"] = report_md(res, data_r4, data_r3, anomalies)
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if committed outputs differ from a fresh build")
    args = ap.parse_args()
    files = outputs()
    if args.check:
        stale = [f for f, body in files.items() if not (ROOT / f).exists() or (ROOT / f).read_text() != body]
        if stale:
            sys.exit("stale or missing outputs: " + ", ".join(stale))
        print(f"OK: {len(files)} outputs match a fresh build")
        return
    for f, body in files.items():
        (ROOT / f).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / f).write_text(body)
        print("wrote", f)


if __name__ == "__main__":
    main()
