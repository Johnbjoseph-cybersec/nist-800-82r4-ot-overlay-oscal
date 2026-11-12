#!/usr/bin/env bash
# Download the NIST PDFs this build reads and check their SHA-256 (they are not committed).
set -euo pipefail
cd "$(dirname "$0")/../sources"
fetch() { curl -fsSL -o "$1" "$2"; echo "$3  $1" | shasum -a 256 -c -; }
fetch NIST.SP.800-82r4.ipd.pdf https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-82r4.ipd.pdf 66e00d5c8dbbfaf0342890e75d2492f72e1ef34da81df5c6a94cc339bd91f683
fetch NIST.SP.800-82r3.pdf https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-82r3.pdf 608f554514d381853e24e0b33123b7080fbd757826f460032690aade63394616
fetch sp800-82r4-ipd-comment-template.xlsx https://csrc.nist.gov/files/pubs/sp/800/82/r4/ipd/docs/sp800-82r4-ipd-comment-template.xlsx 9ab2d0bc2084e8ae84c8ee9b2cc21415b7e94a23cd3366a5d3ef56ecfe5c03b1
