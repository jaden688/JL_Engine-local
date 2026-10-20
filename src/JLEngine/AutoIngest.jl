# ─────────────────────────────────────────────────────────────────────────────
# AutoIngest — native Julia repo scanner & quarry indexer
#
# Replaces the old Python `python3 -c "import sqlite3..."` pattern.
# Walks `jlenginedata/clones/`, classifies every file with multiple dispatch,
# and writes everything into a SQLite quarry the engine owns directly.
#
# Three-tier categorization:
#   CoreComponent       — engine logic, agent profiles, MPF registries
#   ExternalCapability  — tools, scripts, integrations the engine can call
#   TrainingSample      — code that captures the operator's style
#   Documentation       — markdown/rst/txt
#   Configuration       — toml/yaml/env/ini
#   Other               — fallback
#
# Public API:
#   RepoIndexer(db_path, clones_dir)  — open / create the quarry
#   sync_repos!(indexer)              — full scan of clones dir
#   ingest_repo!(indexer, repo_path)  — single repo ingest
#   search_quarry(indexer, query)     — FTS5 search, optional category filter
#   summary(indexer)                  — stats: repo / file counts by category
# ─────────────────────────────────────────────────────────────────────────────

using SQLite, DataFrames, JSON, Dates

# ── File category type hierarchy ─────────────────────────────────────────────
abstract type FileCategory end

struct CoreComponent      <: FileCategory end
struct ExternalCapability <: FileCategory end
struct TrainingSample     <: FileCategory end
struct Documentation      <: FileCategory end
struct Configuration      <: FileCategory end
struct Other              <: FileCategory end

_cat_name(::Type{CoreComponent})      = "core_component"
_cat_name(::Type{ExternalCapability}) = "external_capability"
_cat_name(::Type{TrainingSample})     = "training_sample"
_cat_name(::Type{Documentation})      = "documentation"
_cat_name(::Type{Configuration})      = "configuration"
_cat_name(::Type{Other})              = "other"

# ── RepoIndexer: the live struct the engine holds ───────────────────────────
mutable struct RepoIndexer
    db          :: SQLite.DB
    db_path     :: String
    clones_dir  :: String
    last_sync   :: Union{Nothing, DateTime}
    stats       :: Dict{Symbol, Int}
end

function RepoIndexer(db_path::AbstractString, clones_dir::AbstractString)
    mkpath(dirname(db_path))
    db = SQLite.DB(String(db_path))
    _ensure_quarry_schema!(db)
    return RepoIndexer(db, String(db_path), String(clones_dir), nothing, Dict{Symbol,Int}())
end

function _ensure_quarry_schema!(db::SQLite.DB)
    # CREATE TABLE IF NOT EXISTS — no-op if a previous schema version exists
    SQLite.execute(db, """
        CREATE TABLE IF NOT EXISTS repos (
            full_name    TEXT PRIMARY KEY,
            local_path   TEXT NOT NULL,
            language     TEXT DEFAULT '',
            file_count   INTEGER DEFAULT 0,
            category     TEXT DEFAULT '',
            ingested_at  TEXT NOT NULL
        )
    """)
    SQLite.execute(db, """
        CREATE TABLE IF NOT EXISTS files (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_full_name  TEXT NOT NULL,
            path            TEXT NOT NULL,
            language        TEXT DEFAULT '',
            extension       TEXT DEFAULT '',
            size            INTEGER DEFAULT 0,
            category        TEXT DEFAULT 'other',
            symbols_json    TEXT DEFAULT '[]',
            content         TEXT DEFAULT '',
            updated_at      REAL NOT NULL,
            UNIQUE(repo_full_name, path)
        )
    """)

    # ── Idempotent column migration ──────────────────────────────────────────
    # If an older schema already created `repos` or `files`, the new columns
    # won't exist. Add them defensively. Repeating ADD COLUMN is a no-op (we
    # swallow the "duplicate column name" SQL error per column).
    function _add_col(table::String, col::String, decl::String)
        try
            SQLite.execute(db, "ALTER TABLE $table ADD COLUMN $col $decl")
        catch
            # column already present — fine
        end
    end

    _add_col("repos", "local_path",  "TEXT NOT NULL DEFAULT ''")
    _add_col("repos", "language",    "TEXT DEFAULT ''")
    _add_col("repos", "file_count",  "INTEGER DEFAULT 0")
    _add_col("repos", "category",    "TEXT DEFAULT ''")
    _add_col("repos", "ingested_at", "TEXT DEFAULT ''")

    _add_col("files", "extension",   "TEXT DEFAULT ''")
    _add_col("files", "category",    "TEXT DEFAULT 'other'")
    _add_col("files", "symbols_json","TEXT DEFAULT '[]'")
    _add_col("files", "content",     "TEXT DEFAULT ''")
    _add_col("files", "updated_at",  "REAL DEFAULT 0")
    _add_col("files", "language",    "TEXT DEFAULT ''")
    _add_col("files", "size",        "INTEGER DEFAULT 0")

    # FTS — drop old version if column shape doesn't match, then recreate.
    # Cheap because FTS is rebuilt on next sync anyway.
    try
        SQLite.execute(db, """
            CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                repo_full_name UNINDEXED, path, language, category, symbols, content
            )
        """)
        # Sanity probe — if column shape is wrong, this query will throw
        SQLite.execute(db, "SELECT category FROM files_fts LIMIT 0")
    catch
        try SQLite.execute(db, "DROP TABLE IF EXISTS files_fts") catch drop_err
            @warn "AutoIngest: could not drop stale files_fts" exception=drop_err
        end
        SQLite.execute(db, """
            CREATE VIRTUAL TABLE files_fts USING fts5(
                repo_full_name UNINDEXED, path, language, category, symbols, content
            )
        """)
    end

    # Indexes go last — columns guaranteed to exist by here
    try SQLite.execute(db, "CREATE INDEX IF NOT EXISTS files_repo_idx ON files(repo_full_name)") catch e
        @warn "AutoIngest: files_repo_idx skipped" exception=e
    end
    try SQLite.execute(db, "CREATE INDEX IF NOT EXISTS files_cat_idx  ON files(category)") catch e
        @warn "AutoIngest: files_cat_idx skipped" exception=e
    end
end

# ── Multiple dispatch categorization ─────────────────────────────────────────
# `categorize(path, content)` returns the FileCategory subtype.

function categorize(path::AbstractString, content::AbstractString)::Type{<:FileCategory}
    norm = lowercase(replace(String(path), '\\' => '/'))
    ext  = lowercase(_extension(norm))

    # Tier 1: Core engine components — Julia engine source, agent genome files
    if (ext == ".jl" && (occursin("/jlengine/", norm) || occursin("/byte/src/", norm) ||
                         occursin("/src/app.jl", norm) || occursin("/src/jlengine.jl", norm))) ||
       occursin("_full.json", norm) ||
       endswith(norm, "agents.mpf.json") ||
       endswith(norm, "jlframe_engine_framework.json")
        return CoreComponent
    end

    # Tier 2: External capabilities — anything the engine calls out to
    if occursin("/scripts/", norm) || occursin("/tools/", norm) ||
       occursin("/upgrades/", norm) || occursin("/integrations/", norm) ||
       occursin("/mcp_server/", norm) || occursin("/bridge/", norm)
        return ExternalCapability
    end
    if ext in (".ps1", ".bat", ".sh", ".cmd")
        return ExternalCapability
    end

    # Tier 3: Documentation
    ext in (".md", ".rst", ".txt", ".adoc") && return Documentation

    # Tier 4: Configuration
    ext in (".toml", ".yaml", ".yml", ".ini", ".cfg", ".env") && return Configuration

    # Tier 5: Training samples — operator-style source code (real implementations)
    ext in (".jl", ".py", ".ts", ".tsx", ".js", ".jsx",
            ".rs", ".go", ".rb", ".java", ".cs", ".kt", ".swift",
            ".c", ".cpp", ".h", ".hpp") && return TrainingSample

    return Other
end

# ── Symbol extraction (multiple dispatch by language Val) ────────────────────
extract_symbols(::Val, _content::AbstractString) = String[]

function extract_symbols(::Val{:jl}, content::AbstractString)
    syms = String[]
    for m in eachmatch(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_!]*)"m, String(content))
        push!(syms, m.captures[1])
    end
    for m in eachmatch(r"^\s*struct\s+([A-Za-z_][A-Za-z0-9_]*)"m, String(content))
        push!(syms, m.captures[1])
    end
    for m in eachmatch(r"^\s*mutable\s+struct\s+([A-Za-z_][A-Za-z0-9_]*)"m, String(content))
        push!(syms, m.captures[1])
    end
    return unique(syms)[1:min(end, 32)]
end

function extract_symbols(::Val{:py}, content::AbstractString)
    syms = String[]
    for m in eachmatch(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)"m, String(content))
        push!(syms, m.captures[1])
    end
    for m in eachmatch(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)"m, String(content))
        push!(syms, m.captures[1])
    end
    return unique(syms)[1:min(end, 32)]
end

function extract_symbols(::Val{:ts}, content::AbstractString)
    syms = String[]
    for m in eachmatch(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)", String(content))
        push!(syms, m.captures[1])
    end
    for m in eachmatch(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", String(content))
        push!(syms, m.captures[1])
    end
    for m in eachmatch(r"\bexport\s+(?:const|function|class)\s+([A-Za-z_][A-Za-z0-9_]*)", String(content))
        push!(syms, m.captures[1])
    end
    return unique(syms)[1:min(end, 32)]
end
extract_symbols(::Val{:tsx}, content::AbstractString) = extract_symbols(Val(:ts), content)
extract_symbols(::Val{:js},  content::AbstractString) = extract_symbols(Val(:ts), content)
extract_symbols(::Val{:jsx}, content::AbstractString) = extract_symbols(Val(:ts), content)

function extract_symbols(::Val{:rs}, content::AbstractString)
    syms = String[]
    for m in eachmatch(r"\bfn\s+([A-Za-z_][A-Za-z0-9_]*)", String(content))
        push!(syms, m.captures[1])
    end
    for m in eachmatch(r"\bstruct\s+([A-Za-z_][A-Za-z0-9_]*)", String(content))
        push!(syms, m.captures[1])
    end
    return unique(syms)[1:min(end, 32)]
end

function extract_symbols(::Val{:go}, content::AbstractString)
    syms = String[]
    for m in eachmatch(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)"m, String(content))
        push!(syms, m.captures[1])
    end
    for m in eachmatch(r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+struct"m, String(content))
        push!(syms, m.captures[1])
    end
    return unique(syms)[1:min(end, 32)]
end

# ── Helpers ──────────────────────────────────────────────────────────────────
const _SKIP_DIRS = Set([
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".env",
    "dist", "build", "target", ".next", ".nuxt", ".cache",
    "out", "bin", "obj", ".idea", ".vscode", "coverage",
])

const _LANG_BY_EXT = Dict(
    ".jl"=>"julia", ".py"=>"python", ".ts"=>"typescript", ".tsx"=>"typescript",
    ".js"=>"javascript", ".jsx"=>"javascript", ".rs"=>"rust", ".go"=>"go",
    ".rb"=>"ruby", ".java"=>"java", ".kt"=>"kotlin", ".swift"=>"swift",
    ".c"=>"c", ".cpp"=>"cpp", ".h"=>"c", ".hpp"=>"cpp",
    ".cs"=>"csharp", ".html"=>"html", ".css"=>"css", ".scss"=>"scss",
    ".sh"=>"shell", ".ps1"=>"powershell", ".bat"=>"batch", ".cmd"=>"batch",
    ".md"=>"markdown", ".toml"=>"toml", ".yaml"=>"yaml", ".yml"=>"yaml",
    ".json"=>"json", ".sql"=>"sql", ".rst"=>"rst",
)

function _extension(path::AbstractString)::String
    s = String(path)
    idx = findlast('.', s)
    isnothing(idx) && return ""
    # ignore dotfile-only names like ".env" treated as extension when no other dot
    base = basename(s)
    startswith(base, ".") && count(==('.' ), base) == 1 && return lowercase(base)
    return lowercase(s[idx:end])
end

_lang_for(ext::AbstractString) = get(_LANG_BY_EXT, lowercase(String(ext)), "")

function _looks_binary(content::AbstractString)
    # Sample the head — if there's a NUL byte in the first 4KB, treat as binary
    s = String(content)
    return occursin('\0', SubString(s, 1, min(lastindex(s), 4096)))
end

function _should_skip_dir(root::AbstractString)
    norm = replace(String(root), '\\' => '/')
    for d in _SKIP_DIRS
        occursin("/$d/", norm) && return true
        endswith(norm, "/$d") && return true
    end
    return false
end

# ── Per-repo ingest ──────────────────────────────────────────────────────────
"""
    ingest_repo!(indexer, repo_path; max_files=400, max_filesize=1_048_576)

Scan one repo directory and upsert all categorisable files into the quarry.
Skips: binaries, files larger than `max_filesize`, dirs in `_SKIP_DIRS`.
Returns the number of files ingested for this repo.
"""
function ingest_repo!(indexer::RepoIndexer, repo_path::AbstractString;
                      max_files::Int=400, max_filesize::Int=1_048_576,
                      stats::Dict{Symbol,Int}=Dict{Symbol,Int}())
    isdir(repo_path) || return 0
    repo_name = basename(rstrip(replace(String(repo_path), '\\' => '/'), '/'))
    db = indexer.db
    n_files = 0
    primary_lang = ""
    lang_counts = Dict{String, Int}()

    for (root, dirs, files) in walkdir(String(repo_path); follow_symlinks=false)
        _should_skip_dir(root) && (empty!(dirs); continue)
        # Prune subdirs in-place so walkdir doesn't descend into them
        filter!(d -> !(d in _SKIP_DIRS), dirs)

        for f in files
            n_files >= max_files && break
            full = joinpath(root, f)
            rel  = replace(relpath(full, repo_path), '\\' => '/')

            sz = try filesize(full) catch; 0 end
            (sz == 0 || sz > max_filesize) &&
                (stats[:skipped] = get(stats, :skipped, 0) + 1; continue)

            content = try
                read(full, String)
            catch
                stats[:skipped] = get(stats, :skipped, 0) + 1
                continue
            end

            if _looks_binary(content)
                stats[:skipped] = get(stats, :skipped, 0) + 1
                continue
            end

            cat_t   = categorize(rel, content)
            cat     = _cat_name(cat_t)
            ext     = _extension(rel)
            lang    = _lang_for(ext)
            !isempty(lang) && (lang_counts[lang] = get(lang_counts, lang, 0) + 1)

            sym_lang = isempty(ext) ? :_ : Symbol(strip(ext, '.'))
            symbols = try extract_symbols(Val(sym_lang), content) catch; String[] end

            # Cap stored content at 256KB to keep DB sane on large source files
            stored_content = SubString(content, 1, min(lastindex(content), 262_144))

            try
                SQLite.DBInterface.execute(db, """
                    INSERT INTO files (repo_full_name, path, language, extension, size, category,
                                       symbols_json, content, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(repo_full_name, path) DO UPDATE SET
                        size=excluded.size,
                        category=excluded.category,
                        language=excluded.language,
                        extension=excluded.extension,
                        symbols_json=excluded.symbols_json,
                        content=excluded.content,
                        updated_at=excluded.updated_at
                """, (repo_name, rel, lang, ext, sz, cat,
                      JSON.json(symbols), String(stored_content), time()))

                # Refresh FTS row
                SQLite.DBInterface.execute(db,
                    "DELETE FROM files_fts WHERE repo_full_name = ? AND path = ?",
                    (repo_name, rel))
                SQLite.DBInterface.execute(db, """
                    INSERT INTO files_fts (repo_full_name, path, language, category, symbols, content)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (repo_name, rel, lang, cat, join(symbols, " "), String(stored_content)))

                n_files += 1
                stats[Symbol(cat)] = get(stats, Symbol(cat), 0) + 1
            catch e
                stats[:write_errors] = get(stats, :write_errors, 0) + 1
            end
        end
    end

    # Repo-level row
    if !isempty(lang_counts)
        primary_lang = first(sort(collect(lang_counts), by=x -> -x[2]))[1]
    end

    SQLite.DBInterface.execute(db, """
        INSERT INTO repos (full_name, local_path, language, file_count, category, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(full_name) DO UPDATE SET
            local_path=excluded.local_path,
            language=excluded.language,
            file_count=excluded.file_count,
            ingested_at=excluded.ingested_at
    """, (repo_name, String(repo_path), primary_lang, n_files, "", string(now())))

    return n_files
end

# ── Top-level sync ───────────────────────────────────────────────────────────
"""
    sync_repos!(indexer; max_files_per_repo=400)

Walk `indexer.clones_dir`, ingest every repo found, return aggregate stats.
"""
function sync_repos!(indexer::RepoIndexer; max_files_per_repo::Int=400, max_filesize::Int=1_048_576)
    isdir(indexer.clones_dir) ||
        return Dict{Symbol,Any}(:error => "clones_dir not found: $(indexer.clones_dir)")

    repos = filter(d -> isdir(joinpath(indexer.clones_dir, d)),
                   readdir(indexer.clones_dir))

    @info "AutoIngest: scanning repos" count=length(repos) clones_dir=indexer.clones_dir

    stats = Dict{Symbol,Int}(
        :repos => 0, :files => 0, :skipped => 0, :write_errors => 0,
        :core_component => 0, :external_capability => 0,
        :training_sample => 0, :documentation => 0,
        :configuration => 0, :other => 0,
    )

    t0 = time()
    for repo in repos
        path = joinpath(indexer.clones_dir, repo)
        try
            n = ingest_repo!(indexer, path;
                             max_files=max_files_per_repo,
                             max_filesize=max_filesize, stats=stats)
            stats[:repos] += 1
            stats[:files] += n
        catch e
            @warn "AutoIngest: repo failed" repo=repo exception=(e, catch_backtrace())
        end
    end

    elapsed_s = round(time() - t0; digits=2)
    indexer.last_sync = now()
    indexer.stats = stats
    @info "AutoIngest: sync complete" elapsed_s=elapsed_s repos=stats[:repos] files=stats[:files] skipped=stats[:skipped]
    return stats
end

# ── Search the quarry ───────────────────────────────────────────────────────
"""
    search_quarry(indexer, query; limit=10, category=nothing, repo=nothing)

FTS5 search across all ingested files. Optional filters by category
("core_component" | "external_capability" | "training_sample" | ...) or repo name.
Returns a Vector{Dict} of hits with repo, path, language, category, preview, score.
"""
function search_quarry(indexer::RepoIndexer, query::AbstractString;
                       limit::Int=10,
                       category::Union{Nothing,AbstractString}=nothing,
                       repo::Union{Nothing,AbstractString}=nothing)
    safe_q = "\"" * replace(String(query), "\"" => "") * "\""
    where_extra = String[]
    params = Any[safe_q]
    if !isnothing(category)
        push!(where_extra, "AND f.category = ?")
        push!(params, String(category))
    end
    if !isnothing(repo)
        push!(where_extra, "AND f.repo_full_name = ?")
        push!(params, String(repo))
    end
    push!(params, limit)

    sql = """
        SELECT
            f.repo_full_name AS repo,
            f.path AS path,
            f.language AS language,
            f.category AS category,
            f.symbols_json AS symbols_json,
            snippet(files_fts, 5, '⟦', '⟧', ' ... ', 16) AS preview,
            bm25(files_fts) AS score
        FROM files_fts
        JOIN files f ON f.id = files_fts.rowid
        WHERE files_fts MATCH ? $(join(where_extra, " "))
        ORDER BY score
        LIMIT ?
    """

    hits = Dict{String,Any}[]
    try
        df = DataFrames.DataFrame(SQLite.DBInterface.execute(indexer.db, sql, Tuple(params)))
        for row in eachrow(df)
            push!(hits, Dict{String,Any}(
                "repo"     => row.repo,
                "path"     => row.path,
                "language" => row.language,
                "category" => row.category,
                "symbols"  => try JSON.parse(row.symbols_json) catch; [] end,
                "preview"  => strip(row.preview),
                "score"    => row.score,
            ))
        end
    catch e
        @warn "AutoIngest: search failed" exception=e
    end
    return hits
end

# ── Stats ────────────────────────────────────────────────────────────────────
function quarry_summary(indexer::RepoIndexer)
    db = indexer.db
    repos = first(eachrow(DataFrames.DataFrame(SQLite.DBInterface.execute(db,
        "SELECT COUNT(*) AS n FROM repos")))).n
    files = first(eachrow(DataFrames.DataFrame(SQLite.DBInterface.execute(db,
        "SELECT COUNT(*) AS n FROM files")))).n
    by_cat = Dict{String,Int}()
    for row in eachrow(DataFrames.DataFrame(SQLite.DBInterface.execute(db,
        "SELECT category, COUNT(*) AS n FROM files GROUP BY category")))
        by_cat[row.category] = row.n
    end
    by_lang = Dict{String,Int}()
    for row in eachrow(DataFrames.DataFrame(SQLite.DBInterface.execute(db,
        "SELECT language, COUNT(*) AS n FROM files WHERE language != '' GROUP BY language ORDER BY n DESC LIMIT 10")))
        by_lang[row.language] = row.n
    end
    return Dict{String,Any}(
        "repos"       => Int(repos),
        "files"       => Int(files),
        "by_category" => by_cat,
        "top_langs"   => by_lang,
        "last_sync"   => isnothing(indexer.last_sync) ? "" : string(indexer.last_sync),
        "db_path"     => indexer.db_path,
        "clones_dir"  => indexer.clones_dir,
    )
end
