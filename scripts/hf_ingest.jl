#!/usr/bin/env julia
# HuggingFace dataset ingest — first feed for SparkByte's capability genome.
#
# Pulls models / datasets / spaces from the HF Hub API, license-filters them,
# and writes a JSONL file under data/genome/hf_<kind>.jsonl.
#
# Usage:
#   julia --project=. scripts/hf_ingest.jl [--kind models|datasets|spaces|all]
#                                          [--limit N] [--sort trending|likes|downloads]
#
# Env:
#   HF_TOKEN              optional bearer token (raises rate limit)
#   HF_ALLOWED_LICENSES   comma-list, default: apache-2.0,mit,bsd-3-clause,bsd-2-clause,isc,mpl-2.0,unlicense

using HTTP, JSON3, Dates

const ALLOWED_DEFAULT = ["apache-2.0","mit","bsd-3-clause","bsd-2-clause","isc","mpl-2.0","unlicense"]

const OUT_DIR = joinpath(@__DIR__, "..", "data", "genome")

function _allowed_set()
    raw = strip(get(ENV, "HF_ALLOWED_LICENSES", ""))
    isempty(raw) ? Set(ALLOWED_DEFAULT) : Set(strip.(split(lowercase(raw), ",")))
end

function _headers()
    h = ["Accept"=>"application/json", "User-Agent"=>"SparkByte-Genome/0.1"]
    tok = strip(get(ENV, "HF_TOKEN", ""))
    isempty(tok) || push!(h, "Authorization"=>"Bearer $tok")
    h
end

function _norm_license(x)::String
    x === nothing && return ""
    if x isa AbstractString
        return lowercase(strip(x))
    elseif x isa AbstractVector && !isempty(x)
        return lowercase(strip(string(x[1])))
    end
    ""
end

# Pull a page of items. HF supports `?limit=` up to ~1000 and `?full=true`
# for richer card data. We page via `?limit=N` + `?cursor=` when the API
# returns a Link header (cursor pagination).
function fetch_page(kind::String, limit::Int, sort::String, cursor::Union{String,Nothing})
    base = "https://huggingface.co/api/$(kind)"
    q = ["limit=$(limit)", "full=true", "sort=$(sort)", "direction=-1"]
    cursor !== nothing && push!(q, "cursor=$(HTTP.escapeuri(cursor))")
    url = base * "?" * join(q, "&")
    r = HTTP.get(url, _headers(); readtimeout=30, retry=true, status_exception=false)
    r.status >= 400 && error("HF $(kind) HTTP $(r.status): $(String(r.body)[1:min(200,end)])")
    items = JSON3.read(r.body)
    next_cursor = nothing
    for h in r.headers
        if lowercase(h[1]) == "link"
            m = match(r"<([^>]*cursor=([^&>]+)[^>]*)>;\s*rel=\"next\""i, h[2])
            m !== nothing && (next_cursor = HTTP.unescapeuri(String(m.captures[2])))
        end
    end
    return items, next_cursor
end

function _license_from_tags(tags)
    for t in tags
        s = string(t)
        startswith(lowercase(s), "license:") && return lowercase(strip(s[9:end]))
    end
    ""
end

function row_from(kind::String, item)
    id = string(get(item, :id, ""))
    isempty(id) && return nothing
    card = get(item, :cardData, nothing)
    tags = collect(get(item, :tags, String[]))
    license = _norm_license(card === nothing ? get(item, :license, nothing) : get(card, :license, get(item, :license, nothing)))
    isempty(license) && (license = _license_from_tags(tags))
    Dict(
        "source"      => "huggingface",
        "kind"        => kind,
        "id"          => id,
        "url"         => "https://huggingface.co/" * (kind == "models" ? "" : "$(kind)/") * id,
        "license"     => license,
        "downloads"   => get(item, :downloads, 0),
        "likes"       => get(item, :likes, 0),
        "tags"        => collect(get(item, :tags, String[])),
        "pipeline"    => get(item, :pipeline_tag, nothing),
        "library"     => get(item, :library_name, nothing),
        "updated_at"  => get(item, :lastModified, nothing),
        "ingested_at" => string(now(UTC)),
    )
end

function ingest(kind::String; limit::Int=2000, sort::String="downloads", page_size::Int=200)
    mkpath(OUT_DIR)
    out_path = joinpath(OUT_DIR, "hf_$(kind).jsonl")
    allowed = _allowed_set()
    kept = 0; seen = 0; cursor = nothing
    open(out_path, "w") do io
        while seen < limit
            batch_n = min(page_size, limit - seen)
            items, cursor = fetch_page(kind, batch_n, sort, cursor)
            isempty(items) && break
            for item in items
                seen += 1
                row = row_from(kind, item); row === nothing && continue
                if !isempty(row["license"]) && row["license"] in allowed
                    println(io, JSON3.write(row)); kept += 1
                end
            end
            cursor === nothing && break
            print("\r  $(kind): seen=$(seen) kept=$(kept)"); flush(stdout)
        end
    end
    println("\n✓ $(kind) → $(out_path)  (kept $(kept) / $(seen))")
    return (path=out_path, kept=kept, seen=seen)
end

function main()
    args = ARGS
    kind  = "all"; limit = 2000; sort = "downloads"
    i = 1
    while i <= length(args)
        a = args[i]
        if a == "--kind";   kind  = args[i+1]; i += 2
        elseif a == "--limit"; limit = parse(Int, args[i+1]); i += 2
        elseif a == "--sort";  sort  = args[i+1]; i += 2
        else; i += 1; end
    end
    kinds = kind == "all" ? ["models","datasets","spaces"] : [kind]
    summary = Dict{String,Any}()
    for k in kinds
        try
            r = ingest(k; limit=limit, sort=sort)
            summary[k] = Dict("kept"=>r.kept, "seen"=>r.seen, "path"=>r.path)
        catch e
            @warn "ingest failed" kind=k exception=(e, catch_backtrace())
            summary[k] = Dict("error"=>string(e))
        end
    end
    println("\nSUMMARY:"); println(JSON3.write(summary))
end

abspath(PROGRAM_FILE) == abspath(@__FILE__) && main()
