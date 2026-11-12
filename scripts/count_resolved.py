"""Count controls in each resolved catalog and compare with the overlay data."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
data = json.loads((ROOT / "data/overlay-r4-ipd.json").read_text())
fail = False
for short, lv in (("LOW", "LOW"), ("MOD", "MODERATE"), ("HIGH", "HIGH")):
    want = {c["oscal_id"] for c in data["controls"].values() if c["markers"] and c["markers"].get(short) in ("Select", "Add")}
    cat = json.loads((ROOT / f"overlay/resolved/NIST_SP-800-82r4-ipd_OT-overlay_{lv}_resolved-profile_catalog.json").read_text())["catalog"]
    got, disc = set(), 0

    def walk(cs):
        global disc
        for c in cs:
            got.add(c["id"])
            disc += sum(1 for p in c.get("parts", []) if p.get("name") == "ot-discussion")
            walk(c.get("controls", []))

    for g in cat.get("groups", []):
        walk(g.get("controls", []))
    ok = got == want
    fail |= not ok
    print(f"{lv}: resolved catalog has {len(got)} controls, overlay data has {len(want)}, {disc} OT discussions: {'OK' if ok else 'MISMATCH'}")
sys.exit(1 if fail else 0)
