"""Build a self-contained Bambu Studio profile (resolves inherits and include).

Usage: python3 flatten_profile.py <machine|process|filament> "<profile name>" out.json

Reads the stock profiles from a local Bambu Studio install (macOS path below,
override with BAMBU_PROFILES).
"""
import json
import os
import sys

ROOT = os.environ.get("BAMBU_PROFILES", "/Applications/BambuStudio.app/Contents/Resources/profiles/BBL")


def find(kind, name):
    path = os.path.join(ROOT, kind, name + ".json")
    if os.path.exists(path):
        return path
    # some profiles live in subfolders
    for dirpath, _, files in os.walk(os.path.join(ROOT, kind)):
        if name + ".json" in files:
            return os.path.join(dirpath, name + ".json")
    raise SystemExit("profile not found: %s/%s" % (kind, name))


def load(kind, name):
    with open(find(kind, name)) as f:
        data = json.load(f)
    merged = {}
    if data.get("inherits"):
        merged.update(load(kind, data["inherits"]))
    for inc in data.get("include", []):
        merged.update({k: v for k, v in load(kind, inc).items() if k not in ("name", "type")})
    merged.update(data)
    return merged


if len(sys.argv) != 4:
    raise SystemExit(__doc__)
kind, name, out = sys.argv[1], sys.argv[2], sys.argv[3]
prof = load(kind, name)
prof.pop("inherits", None)
prof.pop("include", None)
prof["name"] = name
prof["from"] = "system"
with open(out, "w") as f:
    json.dump(prof, f, indent=1)
print("ok", out, len(prof), "keys")
