"""One-off, INDEPENDENT computation of the expected demo mapping.

Deliberately imports nothing from `fileorganizer`. Its output (tests/fixtures/demo_expected.json) is
committed and treated as frozen test data; production code never generates the 'standard answer'.
Rerun only if the fixture manifest itself changes.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from make_demo_workspace import DEMO_FILES, content_for  # noqa: E402

PREFIX = "Doc_"
order = sorted(DEMO_FILES, key=lambda t: (t[0].casefold(), t[0]))
mapping = {}
sha = {}
for n, (rel, size, _iso) in enumerate(order, start=1):
    name = rel.split("/")[-1]
    dot = name.rfind(".")
    stem, ext = (name, None) if dot < 0 else (name[:dot], name[dot + 1:])
    new = f"{PREFIX}{stem}_{n:03d}" + ("" if ext is None else "." + ext)
    folder = "no_extension" if ext is None else ext.lower()
    mapping[rel] = f"Organized/{folder}/{new}"
    sha[rel] = hashlib.sha256(content_for(rel, size)).hexdigest()

out = {
    "rules": {"prefix": PREFIX, "numbering": True, "digits": 3, "classify": "extension", "recursive": True},
    "file_count": len(mapping),
    "counts_by_ext": {},
    "mapping": mapping,
    "sha256": sha,
}
for dst in mapping.values():
    out["counts_by_ext"][dst.split("/")[1]] = out["counts_by_ext"].get(dst.split("/")[1], 0) + 1
path = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "demo_expected.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
print(out["file_count"], out["counts_by_ext"])
