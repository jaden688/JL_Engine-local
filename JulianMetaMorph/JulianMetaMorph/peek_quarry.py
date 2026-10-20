import sqlite3
import json

try:
    conn = sqlite3.connect('data/quarry.db')
    conn.row_factory = sqlite3.Row
    
    # Get summary
    repos_count = conn.execute('SELECT COUNT(*) FROM repos').fetchone()[0]
    files_count = conn.execute('SELECT COUNT(*) FROM files').fetchone()[0]
    allowed_count = conn.execute('SELECT COUNT(*) FROM repos WHERE allowed = 1').fetchone()[0]
    
    print(f'📊 Quarry Summary:')
    print(f'   Total Repositories: {repos_count}')
    print(f'   Allowed Repositories: {allowed_count}')
    print(f'   Total Files Indexed: {files_count}\n')
    
    if repos_count > 0:
        print('📂 Repositories in Quarry:')
        repos = conn.execute('SELECT full_name, license_spdx, stars FROM repos LIMIT 10').fetchall()
        for r in repos:
            print(f'   - {r["full_name"]} (License: {r["license_spdx"]}, Stars: {r["stars"]})')
        print()
        
    if files_count > 0:
        print('📄 Sample of Indexed Files:')
        files = conn.execute('SELECT repo_full_name, path, language FROM files LIMIT 10').fetchall()
        for f in files:
            print(f'   - {f["repo_full_name"]} : {f["path"]} ({f["language"]})')
            
except Exception as e:
    print(f'Error reading database: {e}')
