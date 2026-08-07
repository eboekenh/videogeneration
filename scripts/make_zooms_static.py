#!/usr/bin/env python3
import json
import pathlib
import shutil
import sys

P = pathlib.Path('example/images/Odysseus_Uyumlu_Storyboard_V4.json')
if not P.exists():
    print('File not found:', P)
    sys.exit(2)

backup = P.with_suffix('.json.bak')
shutil.copy2(P, backup)
data = json.loads(P.read_text(encoding='utf-8'))
changed = False
count = 0
for scene in data:
    m = scene.get('motion')
    if m in ('zoom_in', 'zoom_out'):
        scene['motion'] = 'static'
        scene['focus_x'] = 0.5
        scene['focus_y'] = 0.5
        changed = True
        count += 1

if changed:
    P.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Updated {count} scenes: zoom -> static. Backup: {backup.name}')
else:
    print('No zoom scenes found to update.')
