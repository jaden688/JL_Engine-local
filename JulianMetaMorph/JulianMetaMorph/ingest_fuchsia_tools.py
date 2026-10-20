"""Ingest the REAL Fuchsia source tools/ folder into MetaMorph's quarry.

This is the actual fuchsia.googlesource.com checkout at ~/fuchsia_os/fuchsia/tools/
NOT the SDK. NOT a GitHub fork. Current source.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from julian_metamorph.scout import JulianMetaMorph
from julian_metamorph.quarry import QuarryStore
from julian_metamorph.models import RepoFile, RepoSnapshot
from collections import defaultdict

quarry = QuarryStore('data/quarry.db')
morph = JulianMetaMorph(quarry=quarry)

# Real Fuchsia source
FUCHSIA_ROOT = Path(r'\\wsl.localhost\kali-linux\home\jadeo\fuchsia_os\fuchsia')
TOOLS_DIR = FUCHSIA_ROOT / 'tools'
ZIRCON_DIR = FUCHSIA_ROOT / 'zircon'
REPO_NAME = 'fuchsia/fuchsia'  # the real one

# Register the real source repo
real_repo = RepoSnapshot(
    full_name=REPO_NAME,
    description='Fuchsia source — REAL current checkout from fuchsia.googlesource.com',
    language='Multi',
    stars=0,
    license_spdx='BSD-3-Clause',
    default_branch='main',
    html_url='https://fuchsia.googlesource.com/fuchsia',
)
quarry.upsert_repo(real_repo, allowed=True)

ext_lang = {
    '.py': 'Python', '.rs': 'Rust', '.go': 'Go',
    '.cc': 'C++', '.cpp': 'C++', '.h': 'C++', '.hpp': 'C++', '.c': 'C',
    '.fidl': 'FIDL', '.cml': 'CML', '.cmx': 'CMX', '.json': 'JSON',
    '.md': 'Markdown', '.gni': 'GN', '.gn': 'GN', '.bzl': 'Bazel',
    '.dart': 'Dart',
}
code_exts = set(ext_lang.keys())
SKIP_DIRS = {'__pycache__', '.git', 'node_modules', 'target', 'build', 'out',
             'third_party', 'prebuilt', 'bazel-bin', 'bazel-out', 'bazel-repos',
             'bazel-workspace'}

# Vulnerability priority keywords for ingest scoring
VRP_KEYWORDS = [
    'TODO(security', 'TODO(sec', 'FIXME(security', 'XXX:', 'HACK:',
    'unsafe', 'validate_resource', 'access check', 'ZX_RSRC',
    'unwrap()', 'expect(', 'panic!', 'unreachable',
    'memcpy', 'strcpy', 'strcat', 'sprintf',
    'race', 'TOCTOU', 'use_after_free', 'double_free',
    'fork', 'clone', 'execve', 'mprotect', 'mmap',
    'sys_pci', 'sys_vmar', 'sys_vmo', 'sys_handle',
    'capability', 'sandbox', 'restricted',
]

def score_file(content: str, path: str) -> int:
    """Higher score = more interesting for VRP."""
    s = 0
    lower = content.lower()
    for kw in VRP_KEYWORDS:
        s += content.count(kw)
    # Path bonuses
    if 'kernel/' in path or 'zircon/' in path: s += 10
    if 'security' in path.lower(): s += 5
    if 'sandbox' in path.lower(): s += 5
    if 'starnix' in path.lower(): s += 8
    if 'syscall' in path.lower(): s += 8
    if 'fidl' in path.lower(): s += 3
    if 'test' in path.lower() or 'mock' in path.lower(): s -= 3
    return s

def ingest_dir(root_dir: Path, label: str, max_files: int | None = None,
               max_size: int = 200_000):
    if not root_dir.exists():
        print(f'SKIP {label}: not found at {root_dir}', flush=True)
        return 0

    print(f'\nScanning {label}...', flush=True)
    candidates = []
    for f in root_dir.rglob('*'):
        if not f.is_file():
            continue
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        if f.suffix not in code_exts:
            continue
        try:
            sz = f.stat().st_size
        except (OSError, PermissionError):
            continue
        if sz > max_size or sz < 50:
            continue
        candidates.append(f)

    print(f'  {label}: {len(candidates)} candidate files', flush=True)

    # Score all candidates and sort
    scored = []
    for f in candidates:
        try:
            content = f.read_text(encoding='utf-8', errors='replace')
            sc = score_file(content, str(f))
            scored.append((sc, f, content))
        except Exception:
            continue

    scored.sort(key=lambda x: -x[0])
    if max_files:
        scored = scored[:max_files]

    print(f'  {label}: ingesting top {len(scored)} by VRP score', flush=True)

    ingested = 0
    for sc, f, content in scored:
        try:
            rel_path = str(f.relative_to(FUCHSIA_ROOT)).replace('\\', '/')
            symbols = morph.extract_symbols(rel_path, content)
            rf = RepoFile(
                path=rel_path,
                content=content,
                language=ext_lang.get(f.suffix, 'Text'),
                sha='',
                size=len(content),
                symbols=symbols,
            )
            quarry.upsert_file(REPO_NAME, rf)
            ingested += 1
            if ingested % 100 == 0:
                print(f'    {label}: {ingested}/{len(scored)} (last: {rel_path}, score={sc})',
                      flush=True)
        except Exception as e:
            pass

    print(f'  {label} done: {ingested} files', flush=True)
    return ingested

# Ingest tools/ first (the user explicitly asked) - cap at 1500
total = 0
total += ingest_dir(TOOLS_DIR, 'tools/', max_files=1500)
# Then the kernel - this is the goldmine for VRP
total += ingest_dir(ZIRCON_DIR / 'kernel', 'zircon/kernel/', max_files=2500)
total += ingest_dir(ZIRCON_DIR / 'system', 'zircon/system/', max_files=1500)

print(f'\n=== TOTAL INGESTED: {total} files ===', flush=True)
print(f'Quarry: {quarry.summary()}', flush=True)

# VRP scan against real source
print('\n=== VRP SCAN against REAL Fuchsia source ===', flush=True)
all_hits = []
seen = set()
for q in morph.VRP_QUERIES:
    hits = morph.scout_task(q, limit=10, allowed_only=False)
    for h in hits:
        if h.repo_full_name == REPO_NAME:  # ONLY current source
            key = f'{h.repo_full_name}:{h.path}'
            if key not in seen:
                seen.add(key)
                all_hits.append(h)

groups = defaultdict(list)
for h in all_hits:
    cat, sub = morph.classify_hit(h)
    groups[f'{cat}/{sub}'].append(h)

print(f'\nREAL-SOURCE FINDINGS: {len(all_hits)} unique across {len(groups)} categories\n', flush=True)
for cat_key in sorted(groups.keys()):
    hits = groups[cat_key]
    print(f'{cat_key}: {len(hits)} findings', flush=True)
    for h in hits[:5]:
        print(f'  -> {h.path}', flush=True)
    if len(hits) > 5:
        print(f'  ... +{len(hits)-5} more', flush=True)
    print(flush=True)
