#!/usr/bin/env python3
import json
from pathlib import Path

bak = Path('example/images/Odysseus_Uyumlu_Storyboard_V4.json.bak')
src = Path('example/images/Odysseus_Uyumlu_Storyboard_V4.json')
if bak.exists():
    p = bak
else:
    p = src

data = json.loads(p.read_text(encoding='utf-8'))
changed = 0
for s in data:
    m = s.get('motion')
    if m == 'zoom_in':
        s['motion'] = 'pan_up'
        changed += 1
    elif m == 'zoom_out':
        s['motion'] = 'pan_down'
        changed += 1
    else:
        # If previously converted to static but has zoom>1, treat as zoom_in -> pan_up
        if m == 'static' and float(s.get('zoom', 1.0)) > 1.0001:
            s['motion'] = 'pan_up'
            changed += 1

out = Path('example/images/Odysseus_with_vertical_pans.json')
out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
print(f'wrote {len(data)} scenes, changed {changed} motions -> {out}')
