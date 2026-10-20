from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from time import time
from typing import TYPE_CHECKING

from .models import RepoFile, RepoSnapshot, ScoutHit

if TYPE_CHECKING:
    pass


class QuarryStore:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS repos (
        full_name TEXT PRIMARY KEY,
        description TEXT DEFAULT '',
        homepage TEXT DEFAULT '',
        language TEXT DEFAULT '',
        stars INTEGER DEFAULT 0,
        forks INTEGER DEFAULT 0,
        topics_json TEXT DEFAULT '[]',
        license_spdx TEXT DEFAULT 'UNKNOWN',
        allowed INTEGER DEFAULT 0,
        default_branch TEXT DEFAULT 'main',
        pushed_at TEXT DEFAULT '',
        html_url TEXT DEFAULT '',
        metadata_json TEXT DEFAULT '{}',
        updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        repo_full_name TEXT NOT NULL,
        path TEXT NOT NULL,
        language TEXT DEFAULT '',
        sha TEXT DEFAULT '',
        size INTEGER DEFAULT 0,
        symbols_json TEXT DEFAULT '[]',
        content TEXT DEFAULT '',
        updated_at REAL NOT NULL,
        UNIQUE(repo_full_name, path)
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
        repo_full_name UNINDEXED,
        path,
        language,
        symbols,
        content
    );
    CREATE TABLE IF NOT EXISTS dataset_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_name TEXT NOT NULL,
        record_id TEXT NOT NULL,
        title TEXT DEFAULT '',
        content TEXT DEFAULT '',
        source TEXT DEFAULT '',
        source_url TEXT DEFAULT '',
        tags_json TEXT DEFAULT '[]',
        metadata_json TEXT DEFAULT '{}',
        created_at REAL NOT NULL,
        UNIQUE(dataset_name, record_id)
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS dataset_records_fts USING fts5(
        dataset_name UNINDEXED,
        record_id UNINDEXED,
        title,
        content,
        source,
        tags
    );
    CREATE TABLE IF NOT EXISTS findings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id   INTEGER REFERENCES findings(id),
        node_type   TEXT NOT NULL DEFAULT 'finding',
        label       TEXT NOT NULL,
        category    TEXT DEFAULT '',
        subcategory TEXT DEFAULT '',
        repo_full_name TEXT DEFAULT '',
        file_path   TEXT DEFAULT '',
        language    TEXT DEFAULT '',
        license_spdx TEXT DEFAULT '',
        preview     TEXT DEFAULT '',
        explanation TEXT DEFAULT '',
        symbols_json TEXT DEFAULT '[]',
        task        TEXT DEFAULT '',
        hunt_id     TEXT DEFAULT '',
        score       REAL DEFAULT 0.0,
        source      TEXT DEFAULT '',
        source_url  TEXT DEFAULT '',
        created_at  REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS findings_hunt ON findings(hunt_id);
    CREATE INDEX IF NOT EXISTS findings_cat  ON findings(category, subcategory);
    CREATE INDEX IF NOT EXISTS findings_parent ON findings(parent_id);
    """

    def __init__(self, db_path: str | Path = "data/quarry.db", *, genome_dir: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.genome_dir = self._resolve_genome_dir(genome_dir)
        self._ensure_schema()
        self._ensure_migrations()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _resolve_genome_dir(self, genome_dir: str | Path | None) -> Path | None:
        if genome_dir is not None:
            path = Path(genome_dir).expanduser()
            return path if path.is_dir() else None
        for candidate in (
            self.db_path.parent / "genome",
            self.db_path.parent.parent / "genome",
        ):
            if candidate.is_dir():
                return candidate
        return None

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(self.SCHEMA)
            conn.commit()

    def _ensure_migrations(self) -> None:
        with self._connect() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(findings)").fetchall()}
            if "source" not in cols:
                conn.execute("ALTER TABLE findings ADD COLUMN source TEXT DEFAULT ''")
            if "source_url" not in cols:
                conn.execute("ALTER TABLE findings ADD COLUMN source_url TEXT DEFAULT ''")
            conn.commit()

    def upsert_repo(self, repo: RepoSnapshot, *, allowed: bool) -> None:
        now = time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO repos (
                    full_name, description, homepage, language, stars, forks, topics_json,
                    license_spdx, allowed, default_branch, pushed_at, html_url, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(full_name) DO UPDATE SET
                    description = excluded.description,
                    homepage = excluded.homepage,
                    language = excluded.language,
                    stars = excluded.stars,
                    forks = excluded.forks,
                    topics_json = excluded.topics_json,
                    license_spdx = excluded.license_spdx,
                    allowed = excluded.allowed,
                    default_branch = excluded.default_branch,
                    pushed_at = excluded.pushed_at,
                    html_url = excluded.html_url,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    repo.full_name,
                    repo.description,
                    repo.homepage,
                    repo.language,
                    repo.stars,
                    repo.forks,
                    json.dumps(list(repo.topics)),
                    repo.license_spdx,
                    int(allowed),
                    repo.default_branch,
                    repo.pushed_at,
                    repo.html_url,
                    json.dumps(repo.metadata),
                    now,
                ),
            )
            conn.commit()

    def upsert_file(self, repo_full_name: str, repo_file: RepoFile) -> None:
        now = time()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM files WHERE repo_full_name = ? AND path = ?",
                (repo_full_name, repo_file.path),
            ).fetchone()
            if existing is not None:
                conn.execute("DELETE FROM files_fts WHERE rowid = ?", (existing["id"],))
                conn.execute("DELETE FROM files WHERE id = ?", (existing["id"],))
            cursor = conn.execute(
                """
                INSERT INTO files (repo_full_name, path, language, sha, size, symbols_json, content, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repo_full_name,
                    repo_file.path,
                    repo_file.language,
                    repo_file.sha,
                    repo_file.size,
                    json.dumps(list(repo_file.symbols)),
                    repo_file.content,
                    now,
                ),
            )
            row_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO files_fts (rowid, repo_full_name, path, language, symbols, content)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    repo_full_name,
                    repo_file.path,
                    repo_file.language,
                    " ".join(repo_file.symbols),
                    repo_file.content,
                ),
            )
            conn.commit()

    def search(self, query: str, *, limit: int = 8, allowed_only: bool = True) -> list[ScoutHit]:
        where = "WHERE r.allowed = 1" if allowed_only else "WHERE 1 = 1"
        sql = f"""
            SELECT
                r.full_name AS repo_full_name,
                r.license_spdx AS license_spdx,
                r.allowed AS allowed,
                f.path AS path,
                f.language AS language,
                f.symbols_json AS symbols_json,
                snippet(files_fts, 4, '', '', ' ... ', 20) AS preview,
                bm25(files_fts) AS score
            FROM files_fts
            JOIN files f ON f.id = files_fts.rowid
            JOIN repos r ON r.full_name = f.repo_full_name
            {where} AND files_fts MATCH ?
            ORDER BY score
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (query, int(limit))).fetchall()
        hits: list[ScoutHit] = []
        for row in rows:
            symbols = json.loads(row["symbols_json"] or "[]")
            hits.append(
                ScoutHit(
                    repo_full_name=row["repo_full_name"],
                    path=row["path"],
                    language=row["language"] or "",
                    license_spdx=row["license_spdx"] or "UNKNOWN",
                    allowed=bool(row["allowed"]),
                    score=float(row["score"]),
                    preview=(row["preview"] or "").strip(),
                    symbols=tuple(symbols if isinstance(symbols, list) else []),
                    why="",
                )
            )
        return hits

    def hf_count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM dataset_records").fetchone()[0])

    def _dataset_value(self, record: dict, *keys: str) -> object:
        for key in keys:
            if key in record and record[key] not in (None, ""):
                return record[key]
        return None

    def _dataset_tags(self, record: dict) -> list[str]:
        values: list[str] = []
        for key in ("tags", "keywords", "labels", "topics", "categories"):
            if key in record:
                value = record[key]
                if isinstance(value, str):
                    values.extend(part.strip() for part in value.split(",") if part.strip())
                elif isinstance(value, (list, tuple, set)):
                    for item in value:
                        if isinstance(item, str) and item.strip():
                            values.append(item.strip())
                elif isinstance(value, dict):
                    values.extend(str(k).strip() for k in value.keys() if str(k).strip())
        if not values and isinstance(record.get("metadata"), dict):
            values.extend(str(k).strip() for k in record["metadata"].keys() if str(k).strip())
        return values[:32]

    def _iter_json_payloads(self, raw: object):
        if isinstance(raw, list):
            for item in raw:
                yield item
            return
        if isinstance(raw, dict):
            for key in ("records", "data", "rows", "items", "results"):
                value = raw.get(key)
                if isinstance(value, list):
                    for item in value:
                        yield item
                    return
            yield raw
            return

    def _ingest_dataset_path(self, path: Path) -> int:
        if not path.exists():
            return 0
        text = path.read_text(encoding="utf-8")
        items: list[object] = []
        try:
            payload = json.loads(text)
            items = list(self._iter_json_payloads(payload))
        except json.JSONDecodeError:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        inserted = 0
        with self._connect() as conn:
            for index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    item = {"text": str(item)}
                dataset_name = str(self._dataset_value(item, "dataset_name", "dataset", "collection", "source_dataset") or path.parent.name or path.stem)
                record_id = str(self._dataset_value(item, "record_id", "id", "uuid", "name", "title", "case_id") or f"{path.stem}-{index}")
                title = str(self._dataset_value(item, "title", "name", "headline", "summary") or record_id)
                content = str(self._dataset_value(item, "content", "text", "body", "description", "details", "excerpt", "summary") or title)
                source = str(self._dataset_value(item, "source", "source_name", "provider") or dataset_name)
                source_url = str(self._dataset_value(item, "source_url", "url", "link", "href", "reference") or "")
                tags = self._dataset_tags(item)
                metadata = {k: v for k, v in item.items() if k not in {"content", "text", "body", "description", "summary", "title", "name", "source", "source_url", "url", "link", "href", "reference", "tags", "keywords", "labels", "topics", "categories"}}
                metadata["source_file"] = str(path.name)
                conn.execute(
                    """
                    INSERT INTO dataset_records (
                        dataset_name, record_id, title, content, source, source_url, tags_json, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(dataset_name, record_id) DO UPDATE SET
                        title = excluded.title,
                        content = excluded.content,
                        source = excluded.source,
                        source_url = excluded.source_url,
                        tags_json = excluded.tags_json,
                        metadata_json = excluded.metadata_json,
                        created_at = excluded.created_at
                    """,
                    (dataset_name, record_id, title, content, source, source_url, json.dumps(tags), json.dumps(metadata), time()),
                )
                row_id = conn.execute(
                    "SELECT id FROM dataset_records WHERE dataset_name = ? AND record_id = ?",
                    (dataset_name, record_id),
                ).fetchone()
                if row_id is not None:
                    conn.execute("DELETE FROM dataset_records_fts WHERE rowid = ?", (row_id["id"],))
                    conn.execute(
                        """
                        INSERT INTO dataset_records_fts (rowid, dataset_name, record_id, title, content, source, tags)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (row_id["id"], dataset_name, record_id, title, content, source, " ".join(tags)),
                    )
                inserted += 1
            conn.commit()
        return inserted

    def ingest_genome(self, *, limit: int | None = None) -> dict[str, int]:
        if not self.genome_dir or not self.genome_dir.exists():
            return {"files_seen": 0, "records_ingested": 0}
        files = sorted(self.genome_dir.glob("**/*"), key=lambda p: str(p))
        ingested = 0
        seen = 0
        for path in files:
            if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".ndjson"}:
                continue
            seen += 1
            ingested += self._ingest_dataset_path(path)
            if limit is not None and ingested >= limit:
                break
        return {"files_seen": seen, "records_ingested": ingested}

    def search_hf(self, query: str, *, limit: int = 8) -> list[dict[str, object]]:
        if not query or query.strip() == "":
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    d.id,
                    d.dataset_name,
                    d.record_id,
                    d.title,
                    d.content,
                    d.source,
                    d.source_url,
                    d.tags_json,
                    d.metadata_json,
                    snippet(dataset_records_fts, 2, '', '', ' ... ', 20) AS preview,
                    bm25(dataset_records_fts) AS score
                FROM dataset_records_fts
                JOIN dataset_records d ON d.id = dataset_records_fts.rowid
                WHERE dataset_records_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (query, int(limit)),
            ).fetchall()
        hits: list[dict[str, object]] = []
        for row in rows:
            tags = json.loads(row["tags_json"] or "[]")
            metadata = json.loads(row["metadata_json"] or "{}")
            source = row["source"] or row["source_url"] or f"hf://{row['dataset_name']}/{row['record_id']}"
            url = row["source_url"] or f"hf://{row['dataset_name']}/{row['record_id']}"
            hits.append({
                "id": row["record_id"],
                "dataset": row["dataset_name"],
                "title": row["title"],
                "content": row["content"],
                "source": source,
                "source_url": row["source_url"],
                "url": url,
                "license": "dataset",
                "downloads": 0,
                "likes": 0,
                "pipeline": row["dataset_name"],
                "library": "huggingface-dataset",
                "jm_role": row["source"] or row["dataset_name"],
                "jm_capability": ", ".join(tags) if isinstance(tags, list) else str(tags),
                "jm_metadata": {"dataset_name": row["dataset_name"], "record_id": row["record_id"], "tags": tags, **metadata},
                "score": float(row["score"]),
                "preview": (row["preview"] or row["content"] or row["title"])[:400],
            })
        return hits

    def summary(self) -> dict[str, int]:
        with self._connect() as conn:
            repos = int(conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0])
            files = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
            allowed = int(conn.execute("SELECT COUNT(*) FROM repos WHERE allowed = 1").fetchone()[0])
            findings = int(conn.execute("SELECT COUNT(*) FROM findings WHERE node_type='finding'").fetchone()[0])
            dataset_records = int(conn.execute("SELECT COUNT(*) FROM dataset_records").fetchone()[0])
        return {"repos": repos, "files": files, "allowed_repos": allowed, "findings": findings, "dataset_records": dataset_records}

    # ── FINDINGS TREE ─────────────────────────────────────────────────────────
    def store_hunt_findings(
        self,
        *,
        hunt_id: str,
        task: str,
        hits: list[ScoutHit],
        queries: list[str],
    ) -> int:
        """
        Stores hits into the findings tree under:
          root (hunt) → category node → subcategory node → finding leaf
        Returns number of finding leaves stored.
        """
        from .scout import JulianMetaMorph  # avoid circular at module level

        now = time()
        with self._connect() as conn:
            # Root node for this hunt
            cur = conn.execute(
                """INSERT INTO findings (parent_id, node_type, label, task, hunt_id, created_at)
                   VALUES (NULL, 'hunt', ?, ?, ?, ?)""",
                (f"Hunt: {task[:60]}", task, hunt_id, now),
            )
            hunt_node_id = cur.lastrowid

            # category_key → node id cache
            cat_nodes: dict[str, int] = {}
            subcat_nodes: dict[str, int] = {}

            for hit in hits:
                cat, subcat = JulianMetaMorph.classify_hit(hit)
                explanation = JulianMetaMorph.explain_hit(task, hit)

                # Ensure category node
                if cat not in cat_nodes:
                    c = conn.execute(
                        """INSERT INTO findings (parent_id, node_type, label, category, task, hunt_id, created_at)
                           VALUES (?, 'category', ?, ?, ?, ?, ?)""",
                        (hunt_node_id, cat.replace("_", " ").upper(), cat, task, hunt_id, now),
                    )
                    cat_nodes[cat] = c.lastrowid

                # Ensure subcategory node
                subcat_key = f"{cat}:{subcat}"
                if subcat_key not in subcat_nodes:
                    s = conn.execute(
                        """INSERT INTO findings (parent_id, node_type, label, category, subcategory, task, hunt_id, created_at)
                           VALUES (?, 'subcategory', ?, ?, ?, ?, ?, ?)""",
                        (cat_nodes[cat], subcat.replace("_", " "), cat, subcat, task, hunt_id, now),
                    )
                    subcat_nodes[subcat_key] = s.lastrowid

                # Finding leaf
                conn.execute(
                    """INSERT INTO findings
                        (parent_id, node_type, label, category, subcategory,
                         repo_full_name, file_path, language, license_spdx,
                         preview, explanation, symbols_json, task, hunt_id, score,
                         source, source_url, created_at)
                        VALUES (?, 'finding', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        subcat_nodes[subcat_key],
                        hit.path.split("/")[-1],
                        cat, subcat,
                        hit.repo_full_name,
                        hit.path,
                        hit.language,
                        hit.license_spdx,
                        hit.preview[:600],
                        explanation,
                        json.dumps(list(hit.symbols)),
                        task,
                        hunt_id,
                        hit.score,
                        hit.source or hit.repo_full_name,
                        hit.source_url or hit.path,
                        now,
                    ),
                )
            conn.commit()
        return len(hits)

    def get_findings_tree(self, *, hunt_id: str | None = None) -> list[dict]:
        """
        Returns all findings nodes as a flat list with parent_id so the client
        can build any tree structure it wants.
        Optionally filtered to a single hunt_id.
        """
        where = "WHERE hunt_id = ?" if hunt_id else ""
        params = (hunt_id,) if hunt_id else ()
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT id, parent_id, node_type, label, category, subcategory,
                            repo_full_name, file_path, language, license_spdx,
                            preview, explanation, symbols_json, task, hunt_id, score,
                            source, source_url, created_at
                     FROM findings {where}
                     ORDER BY created_at DESC, id ASC""",
                params,
            ).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "parent_id": r["parent_id"],
                "node_type": r["node_type"],
                "label": r["label"],
                "category": r["category"],
                "subcategory": r["subcategory"],
                "repo_full_name": r["repo_full_name"],
                "file_path": r["file_path"],
                "language": r["language"],
                "license_spdx": r["license_spdx"],
                "preview": r["preview"],
                "explanation": r["explanation"],
                "symbols": json.loads(r["symbols_json"] or "[]"),
                "task": r["task"],
                "hunt_id": r["hunt_id"],
                "score": r["score"],
                "source": r["source"],
                "source_url": r["source_url"],
                "created_at": r["created_at"],
            })
        return result

    def list_hunts(self) -> list[dict]:
        """Returns summary rows for each unique hunt_id."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT hunt_id, task, created_at,
                          COUNT(CASE WHEN node_type='finding' THEN 1 END) AS finding_count
                   FROM findings
                   GROUP BY hunt_id
                   ORDER BY created_at DESC""",
            ).fetchall()
        return [
            {"hunt_id": r["hunt_id"], "task": r["task"],
             "finding_count": r["finding_count"], "created_at": r["created_at"]}
            for r in rows
        ]
