"""Ingest Fuchsia SDK directly from local WSL filesystem into MetaMorph quarry."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from julian_metamorph.scout import JulianMetaMorph
from julian_metamorph.quarry import QuarryStore
from julian_metamorph.models import RepoFile, RepoSnapshot
from collections import defaultdict

quarry = QuarryStore('data/quarry.db')
morph = JulianMetaMorph(quarry=quarry)

SDK_ROOT = Path(r'\\wsl.localhost\kali-linux\home\jadeo\fuchsia-sdk\core')

# Register the SDK as a repo
sdk_repo = RepoSnapshot(
    full_name='google/fuchsia-sdk',
    description='Fuchsia SDK - FIDL protocols, C++ headers, bindings',
    language='C++',
    stars=0,
    license_spdx='MIT',
    default_branch='local',
    html_url='https://fuchsia.dev',
)
quarry.upsert_repo(sdk_repo, allowed=True)

# Ingest ALL FIDL files
fidl_dir = SDK_ROOT / 'fidl'
fidl_files = list(fidl_dir.rglob('*.fidl'))
print(f'Found {len(fidl_files)} FIDL files. Ingesting...', flush=True)

ingested = 0
for f in fidl_files:
    try:
        content = f.read_text(encoding='utf-8', errors='replace')
        rel_path = str(f.relative_to(SDK_ROOT)).replace('\\', '/')
        symbols = morph.extract_symbols(rel_path, content)
        rf = RepoFile(path=rel_path, content=content, language='FIDL', sha='', size=len(content), symbols=symbols)
        quarry.upsert_file('google/fuchsia-sdk', rf)
        ingested += 1
        if ingested % 100 == 0:
            print(f'  FIDL: {ingested}/{len(fidl_files)}', flush=True)
    except Exception as e:
        pass

print(f'FIDL ingested: {ingested}', flush=True)

# Ingest C++ headers from pkg/
pkg_dir = SDK_ROOT / 'pkg'
cpp_files = list(pkg_dir.rglob('*.h')) + list(pkg_dir.rglob('*.cc')) + list(pkg_dir.rglob('*.cpp'))
print(f'Found {len(cpp_files)} C/C++ files in pkg/. Ingesting...', flush=True)

cpp_ingested = 0
for f in cpp_files:
    try:
        content = f.read_text(encoding='utf-8', errors='replace')
        rel_path = str(f.relative_to(SDK_ROOT)).replace('\\', '/')
        symbols = morph.extract_symbols(rel_path, content)
        suffix = f.suffix.lstrip('.')
        lang_map = {'h': 'C++', 'cc': 'C++', 'cpp': 'C++', 'c': 'C'}
        rf = RepoFile(path=rel_path, content=content, language=lang_map.get(suffix, 'C++'), sha='', size=len(content), symbols=symbols)
        quarry.upsert_file('google/fuchsia-sdk', rf)
        cpp_ingested += 1
        if cpp_ingested % 100 == 0:
            print(f'  C++: {cpp_ingested}/{len(cpp_files)}', flush=True)
    except Exception as e:
        pass

print(f'C++ ingested: {cpp_ingested}', flush=True)
print(f'\nTotal quarry now: {quarry.summary()}', flush=True)

# Full VRP scan
print('\n=== VRP SCAN (with SDK data) ===', flush=True)
all_hits = []
seen = set()
for q in morph.VRP_QUERIES:
    hits = morph.scout_task(q, limit=10, allowed_only=False)
    for h in hits:
        key = f'{h.repo_full_name}:{h.path}'
        if key not in seen:
            seen.add(key)
            all_hits.append(h)

groups = defaultdict(list)
for h in all_hits:
    cat, sub = morph.classify_hit(h)
    groups[f'{cat}/{sub}'].append(h)

print(f'TOTAL: {len(all_hits)} unique findings across {len(groups)} categories\n', flush=True)
for cat_key in sorted(groups.keys()):
    hits = groups[cat_key]
    print(f'{cat_key}: {len(hits)} findings', flush=True)
    for h in hits[:3]:
        print(f'  -> {h.path}', flush=True)
        print(f'     symbols: {list(h.symbols[:5])}', flush=True)
    if len(hits) > 3:
        print(f'  ... +{len(hits)-3} more', flush=True)
    print(flush=True)
