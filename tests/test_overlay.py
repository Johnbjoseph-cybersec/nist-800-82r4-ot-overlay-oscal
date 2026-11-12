"""Tests for the SP 800-82r4 ipd OT overlay rendering. Run: python3 -m unittest discover -s tests -v

Tests marked SOURCE need sources/*.pdf (scripts/fetch_sources.sh) and poppler; they FAIL, not skip,
when the sources are missing, so a green run always means the PDF checks ran.
"""

import copy
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import checks  # noqa: E402
import overlay as ov  # noqa: E402

IDX = checks.catalog_index(build.CATALOG)
DATA = json.loads((ROOT / "data/overlay-r4-ipd.json").read_text())
DATA3 = json.loads((ROOT / "data/overlay-r3.json").read_text())
FIX = json.loads((ROOT / "tests/fixtures/wrong-id-rows.json").read_text())
LEVEL_FILE = build.LEVEL_FILE


def rows(data):
    return {k: {"markers": c["markers"] or {}, "page": c.get("table_pdf_page")} for k, c in data["controls"].items() if c.get("markers") is not None}


def load_profile(lv):
    return json.loads((ROOT / f"overlay/NIST_SP-800-82r4-ipd_OT-overlay_{LEVEL_FILE[lv]}_profile.json").read_text())


class IdChecks(unittest.TestCase):
    def test_wrong_id_fixture_fails(self):
        problems = checks.check_ids(FIX["rows"], IDX, ov.oscal_id)
        flagged = sorted({p.split(":")[0] for p in problems})
        self.assertEqual(flagged, sorted(FIX["expect_bad"]))

    def test_wrong_id_in_profile_fails(self):
        prof = copy.deepcopy(load_profile("LOW"))
        prof["profile"]["imports"][0]["include-controls"][0]["with-ids"].append("ac-2.99")
        prof["profile"]["modify"]["alters"].append({"control-id": "sc-46.7", "adds": []})
        bad = build.verify_profile(prof, IDX)
        self.assertTrue(any("ac-2.99" in b for b in bad), bad)
        self.assertTrue(any("sc-46.7" in b for b in bad), bad)

    def test_every_extracted_id_is_in_catalog(self):
        self.assertEqual(checks.check_ids(rows(DATA), IDX, ov.oscal_id), [])
        self.assertEqual(checks.check_ids(rows(DATA3), IDX, ov.oscal_id), [])

    def test_committed_profiles_verify(self):
        for lv in ov.LEVELS:
            self.assertEqual(build.verify_profile(load_profile(lv), IDX), [], lv)


class Counts(unittest.TestCase):
    def test_overlay_equals_53b_minus_remove_plus_add(self):
        expected = {"LOW": 160, "MOD": 304, "HIGH": 387}
        for lv in ov.LEVELS:
            base = checks.baseline_ids(build.VENDOR / f"NIST_SP-800-53_rev5_{LEVEL_FILE[lv]}-baseline_profile.json")
            r = rows(DATA)
            sel = {ov.oscal_id(k) for k in checks.marked(r, lv, {"Select", "Add"})}
            add = {ov.oscal_id(k) for k in checks.marked(r, lv, {"Add"})}
            rem = {ov.oscal_id(k) for k in checks.marked(r, lv, {"Remove"})}
            self.assertEqual(sel, (base - rem) | add, lv)
            self.assertEqual(len(sel), expected[lv], lv)
            ids = load_profile(lv)["profile"]["imports"][0]["include-controls"][0]["with-ids"]
            self.assertEqual(set(ids), sel, lv)


class DetectorsFire(unittest.TestCase):
    """Each consistency check must report a planted error, so its zero in the report is earned."""

    def test_summary_vs_detailed_detects_missing_and_extra(self):
        r = rows(DATA)
        summary = {lv: {k: [1] for k in DATA["summary_table"][lv]} for lv in ov.LEVELS}
        self.assertEqual(checks.summary_vs_detailed(summary, r), [])
        summary["MOD"].pop("AC-2(13)")
        summary["LOW"]["SC-7(3)"] = [1]
        kinds = {(f["level"], f["label"], f["kind"]) for f in checks.summary_vs_detailed(summary, r)}
        self.assertIn(("MOD", "AC-2(13)", "detailed-only"), kinds)
        self.assertIn(("LOW", "SC-7(3)", "summary-only"), kinds)

    def test_53b_check_detects_bad_select_and_dropped_control(self):
        base = {lv: checks.baseline_ids(build.VENDOR / f"NIST_SP-800-53_rev5_{LEVEL_FILE[lv]}-baseline_profile.json") for lv in ov.LEVELS}
        priv = checks.baseline_ids(build.VENDOR / "NIST_SP-800-53_rev5_PRIVACY-baseline_profile.json")
        r = copy.deepcopy(rows(DATA))
        self.assertEqual(checks.detailed_vs_53b(r, base, priv, ov.oscal_id), [])
        r["AC-3(11)"]["markers"]["HIGH"] = "Select"  # not in 53B HIGH
        del r["AC-2"]["markers"]["LOW"]  # 53B control left unmarked
        kinds = {(f["level"], f["id"], f["kind"]) for f in checks.detailed_vs_53b(r, base, priv, ov.oscal_id)}
        self.assertIn(("HIGH", "ac-3.11", "select-not-in-53B"), kinds)
        self.assertIn(("LOW", "ac-2", "53B-control-unmarked"), kinds)

    def test_edition_diff_detects_marker_change(self):
        r4, r3 = rows(DATA), rows(DATA3)
        self.assertEqual(checks.edition_diff(r3, r4), [])
        r4 = copy.deepcopy(r4)
        r4["SC-10"]["markers"]["HIGH"] = "Select"
        self.assertEqual([f["label"] for f in checks.edition_diff(r3, r4)], ["SC-10"])


class Source(unittest.TestCase):
    """SOURCE tests: need sources/*.pdf and poppler."""

    @classmethod
    def setUpClass(cls):
        pdf = ROOT / "sources" / ov.R4.pdf_name
        if not pdf.exists():
            raise AssertionError(f"{pdf} missing: run scripts/fetch_sources.sh (these tests do not skip)")
        raw = subprocess.run(["pdftotext", str(pdf), "-"], check=True, capture_output=True, text=True).stdout
        # drop running headers/footers and the line-number and page-number columns, which raw mode
        # interleaves into sentences at page breaks; nothing else is removed
        keep = [ln for ln in raw.split("\n")
                if not re.fullmatch(r"\s*\d+\s*", ln)
                and not re.fullmatch(r"\s*(NIST SP 800-82r4 ipd \(Initial Public Draft\)|September 2026|Guide to OT Security)\s*", ln)]
        cls.text = "\n".join(keep)

    @staticmethod
    def norm(t):
        t = t.replace("’", "'").replace("“", '"').replace("”", '"')
        # pdftotext's raw mode drops a hyphen at a line end ("read-" / "only" -> "readonly") while the
        # extractor keeps it ("read-only"); a line-end hyphen is ambiguous in a PDF, so compare without hyphens
        return re.sub(r"[\s\-\u2010\u2011\u2013]+", "", t)

    def test_every_discussion_and_rationale_is_quoted_from_the_pdf(self):
        hay = self.norm(self.text)
        missing = []
        for k, c in DATA["controls"].items():
            texts = ([c["ot_discussion"]] if c["ot_discussion"] else []) + [r["text"] for r in c["rationale"]]
            missing += [k for t in texts if self.norm(t) not in hay]
        self.assertEqual(missing, [])

    def test_build_is_reproducible(self):
        out = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/build.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
