#!/bin/bash
# Build individual skill ZIPs and the complete course kit from current sources.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import json
from pathlib import Path
import zipfile

root=Path.cwd()
out=root/'dist';out.mkdir(exist_ok=True)
def archive(name, files):
    target=out/name
    temporary=out/(name+'.tmp')
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for dest,source in sorted(files):
            entry=zipfile.ZipInfo(dest,date_time=(2026,11,7,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED
            entry.external_attr=0o644<<16
            z.writestr(entry,source.read_bytes())
    with zipfile.ZipFile(temporary) as z:
        assert z.testzip() is None
    temporary.replace(target)
    print(name)

for folder in sorted((root/'skills').iterdir()):
    if not (folder/'SKILL.md').is_file():continue
    files=[(folder.name+'/'+p.relative_to(folder).as_posix(),p) for p in folder.rglob('*') if p.is_file() and p.name!='.DS_Store']
    archive(folder.name+'.zip',files)

data=json.loads((root/'courses/reels/catalog.json').read_text())
files=[]
for group in data['groups']:
    for item in group['skills']:
        folder=root/'skills'/item['slug']
        assert (folder/'SKILL.md').is_file(),folder
        files.extend((p.relative_to(root).as_posix(),p) for p in folder.rglob('*') if p.is_file() and p.name!='.DS_Store')
files.extend((p.relative_to(root).as_posix(),p) for p in (root/'courses/reels').rglob('*') if p.is_file())
archive('reel-course-kit.zip',files)
PY
