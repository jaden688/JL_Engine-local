import sqlite3
conn = sqlite3.connect(r'C:\Users\J_lin\Desktop\jl-engine-reboot-reboot\JL_Engine-SB.Omni\sparkbyte_memory.db')
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("TABLES:", tables)

for t in ['memory', 'thoughts', 'knowledge', 'intentions']:
    if t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        count = cur.fetchone()[0]
        print(f"\n=== {t.upper()} ({count} rows) ===")
        if t == 'memory':
            cur.execute("SELECT id, tag, substr(content,1,250) FROM memory WHERE tag NOT IN ('self_src','self_tree') ORDER BY id DESC LIMIT 8")
        elif t == 'thoughts':
            cur.execute("SELECT id, type, substr(thought,1,400) FROM thoughts ORDER BY id DESC LIMIT 6")
        elif t == 'knowledge':
            cur.execute("SELECT id, domain, topic, substr(content,1,200) FROM knowledge ORDER BY id DESC LIMIT 6")
        elif t == 'intentions':
            cur.execute("SELECT id, intent, status FROM intentions ORDER BY id DESC LIMIT 6")
        for row in cur.fetchall():
            print(row)

conn.close()
