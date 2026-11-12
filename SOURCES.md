# Sources

Every input to the build, with where it came from and its SHA-256. `scripts/build.py` refuses to run
if a PDF's hash differs; `scripts/fetch_sources.sh` downloads and checks them.

| Input | URL | Accessed | SHA-256 |
|---|---|---|---|
| NIST SP 800-82 Rev. 4 initial public draft (21 Sep 2026), 321 pp. | https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-82r4.ipd.pdf (landing page https://csrc.nist.gov/pubs/sp/800/82/r4/ipd) | 2026-11-12 | 66e00d5c8dbbfaf0342890e75d2492f72e1ef34da81df5c6a94cc339bd91f683 |
| NIST SP 800-82 Rev. 3 (Sep 2023) | https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-82r3.pdf | 2026-11-12 | 608f554514d381853e24e0b33123b7080fbd757826f460032690aade63394616 |
| SP 800-82r4 ipd comment template | https://csrc.nist.gov/files/pubs/sp/800/82/r4/ipd/docs/sp800-82r4-ipd-comment-template.xlsx | 2026-11-12 | 9ab2d0bc2084e8ae84c8ee9b2cc21415b7e94a23cd3366a5d3ef56ecfe5c03b1 |
| SP 800-53 Rev. 5 catalog, OSCAL JSON (release 5.2.0, OSCAL 1.2.3) | usnistgov/oscal-content @ f0de6d8d8c059d374f15e0ae07508d82e370fc1d, `nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json` | 2026-11-12 | 64ca6b4161de51ab6af098a7d101d326f14c95e1abf721396cd8a049e8115eeb |
| SP 800-53B LOW baseline profile | same commit, `NIST_SP-800-53_rev5_LOW-baseline_profile.json` | 2026-11-12 | cfd4f5d9a192eb42dc04b745d82f95a85926a2a85a45418034a380a42bda9424 |
| SP 800-53B MODERATE baseline profile | same commit, `NIST_SP-800-53_rev5_MODERATE-baseline_profile.json` | 2026-11-12 | e3a0f11237cfaac24dfcf1586e07683f17423757fd84208deb33196b12e8f590 |
| SP 800-53B HIGH baseline profile | same commit, `NIST_SP-800-53_rev5_HIGH-baseline_profile.json` | 2026-11-12 | d2ef340986b9f1ee820ad866a0f964d9a9d1088b24080c74b795ddb0148b9f83 |
| SP 800-53B PRIVACY baseline profile | same commit, `NIST_SP-800-53_rev5_PRIVACY-baseline_profile.json` | 2026-11-12 | c0e3d54d9f474bc6c33338a8e524bc52ad070f94f9274db7ec48242242fecacc |

Tools: poppler `pdftotext` / `pdftohtml` 26.10.0; Python 3 standard library (tested with 3.15.0);
oscal-cli 3.2.0 (liboscal-java 7.2.0) on OpenJDK 21 for validation.

Where the r4 ipd is quoted: Appendix E (PDF pages 222-310, printed pages 204-292). Printed page =
PDF page - 18. Line numbers in `data/` are the draft's own margin line numbers.
