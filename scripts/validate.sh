#!/usr/bin/env bash
# Validate and resolve every overlay profile with oscal-cli, then validate the resolved catalogs
# and check their control counts. Usage: OSCAL_CLI=/path/to/oscal-cli scripts/validate.sh
set -euo pipefail
cd "$(dirname "$0")/.."
OSCAL_CLI="${OSCAL_CLI:-oscal-cli}"
mkdir -p overlay/resolved
"$OSCAL_CLI" --version --no-color | head -1
for lv in LOW MODERATE HIGH; do
  p="overlay/NIST_SP-800-82r4-ipd_OT-overlay_${lv}_profile.json"
  r="overlay/resolved/NIST_SP-800-82r4-ipd_OT-overlay_${lv}_resolved-profile_catalog.json"
  "$OSCAL_CLI" validate --no-color "$p"
  "$OSCAL_CLI" resolve-profile --no-color --to=json --overwrite "$p" "$r"
  "$OSCAL_CLI" validate --no-color "$r"
done
python3 -I scripts/count_resolved.py
