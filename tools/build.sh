#!/bin/bash
# Pack every skills/<name>/ into dist/<name>.zip for upload to claude.ai
# (Settings → Capabilities → Skills). The zip holds the <name>/ folder itself.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
rm -f dist/*.zip
for d in skills/*/; do
  name=$(basename "$d")
  [ -f "$d/SKILL.md" ] || { echo "skip $name: no SKILL.md" >&2; continue; }
  python3 - "$name" <<'PY'
import sys, zipfile, pathlib
name = sys.argv[1]
src = pathlib.Path("skills") / name
with zipfile.ZipFile(f"dist/{name}.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(src.rglob("*")):
        if f.is_file() and f.name != ".DS_Store":
            z.write(f, f.relative_to("skills"))
PY
  echo "dist/$name.zip"
done
