"""Ingest EVERYTHING from Fuchsia SDK — bind/, obj/, arch/ directories."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from julian_metamorph.scout import JulianMetaMorph
from julian_metamorph.quarry import QuarryStore
from julian_metamorph.models import RepoFile
from collections import defaultdict

quarry = QuarryStore('data/quarry.db')
morph = JulianMetaMorph(quarry=quarry)

SDK_ROOT = Path(r'\\wsl.localhost\kali-linux\home\jadeo\fuchsia-sdk\core')
REPO_NAME = 'google/fuchsia-sdk'

lang_map = {'.h': 'C++', '.cc': 'C++', '.cpp': 'C++', '.c': 'C', '.fidl': 'FIDL', '.bind': 'Bind'}
code_exts = {'.h', '.cc', '.cpp', '.c', '.fidl', '.bind'}

# Directories we haven't ingested yet
dirs_to_ingest = ['bind', 'obj', 'arch']

total_ingested = 0
for dirname in dirs_to_ingest:
    target_dir = SDK_ROOT / dirname
    if not target_dir.exists():
        print(f'SKIP {dirname}: not found', flush=True)
        continue

    files = [f for f in target_dir.rglob('*') if f.suffix in code_exts and f.is_file() and f.stat().st_size < 150000]
    print(f'{dirname}/: {len(files)} files to ingest', flush=True)

    ingested = 0
    for f in files:
        try:
            content = f.read_text(encoding='utf-8', errors='replace')
            rel_path = str(f.relative_to(SDK_ROOT)).replace('\\', '/')
            symbols = morph.extract_symbols(rel_path, content)
            rf = RepoFile(
                path=rel_path,
                content=content,
                language=lang_map.get(f.suffix, 'C++'),
                sha='',
                size=len(content),
                symbols=symbols,
            )
            quarry.upsert_file(REPO_NAME, rf)
            ingested += 1
            if ingested % 250 == 0:
                print(f'  {dirname}: {ingested}/{len(files)}', flush=True)
        except Exception:
            pass

    total_ingested += ingested
    print(f'  {dirname} done: {ingested} files', flush=True)

print(f'\nTotal new files ingested: {total_ingested}', flush=True)
print(f'Quarry: {quarry.summary()}', flush=True)

# Full VRP scan with everything
print('\n=== FULL VRP SCAN (everything) ===', flush=True)
all_hits = []
seen = set()
for q in morph.VRP_QUERIES:
    hits = morph.scout_task(q, limit=15, allowed_only=False)
    for h in hits:
        key = f'{h.repo_full_name}:{h.path}'
        if key not in seen:
            seen.add(key)
            all_hits.append(h)

groups = defaultdict(list)
for h in all_hits:
    cat, sub = morph.classify_hit(h)
    groups[f'{cat}/{sub}'].append(h)

print(f'\nTOTAL: {len(all_hits)} unique findings across {len(groups)} categories\n', flush=True)

priority_order = ['vrp_sandbox', 'vrp_starnix', 'vrp_zircon', 'vrp_fidl', 'vrp_memory', 'vrp_concurrency', 'vrp_driver', 'vrp_network']
for cat_key in sorted(groups.keys(), key=lambda k: (priority_order.index(k.split('/')[0]) if k.split('/')[0] in priority_order else 99)):
    hits = groups[cat_key]
    print(f'{cat_key}: {len(hits)} findings', flush=True)
    for h in hits[:5]:
        print(f'  -> {h.path}', flush=True)
        print(f'     symbols: {list(h.symbols[:5])}', flush=True)
    if len(hits) > 5:
        print(f'  ... +{len(hits)-5} more', flush=True)
    print(flush=True)
