# Webula dependency intelligence / portable Julia-only scanner.
# Tree edges are owned by ui.html; these are typed semantic relationships.
# Bounded scan and size limits avoid indexing caches, databases and secrets.
const _WB_CODE_EXTS = Set((".jl",".py",".js",".jsx",".ts",".tsx",".mjs",".cjs",".json",".toml"))
const _WB_EXCLUDED_DIRS = Set((".git","node_modules",".CondaPkg",".pixi",".next","dist",
    "build","release","runtime_test","venv",".venv","__pycache__",".pytest_cache",".vscode"))
const _WB_SOURCE_SUFFIXES = (".jl",".py",".js",".jsx",".ts",".tsx",".mjs",".cjs",".json",".toml")
const _WB_RESOLVE_SUFFIXES = ("",".jl",".py",".ts",".tsx",".js",".jsx",".mjs",".cjs",
    "/index.ts","/index.tsx","/index.js","/__init__.py")
function _wb_resolve_import(origin::String, spec::String, files::Set{String};
                            language::String="", kind::String="import",
                            julia_modules::Dict{String,String}=Dict{String,String}())
    cleaned = strip(spec)
    isempty(cleaned) && return nothing
    if language == "jl" && kind == "import"
        token = replace(cleaned, r"^\.+"=>"")
        haskey(julia_modules, token) && return julia_modules[token]
    end
    candidates = String[]
    base = dirname(origin)
    if language == "py" && startswith(cleaned, ".")
        m = match(r"^(\.+)(.*)$", cleaned)
        m === nothing && return nothing
        dots = length(m.captures[1])
        for _ in 2:dots
            base = dirname(base)
        end
        path = replace(m.captures[2], "."=>"/")
        push!(candidates, normpath(joinpath(base, path)))
    elseif startswith(cleaned, ".") || startswith(cleaned, "/") || kind == "include"
        push!(candidates, normpath(joinpath(base, cleaned)))
    elseif language == "py"
        rel = replace(cleaned, "."=>"/")
        push!(candidates, normpath(rel))
        push!(candidates, normpath(joinpath(base, rel)))
    else
        return nothing
    end
    for candidate in candidates, suffix in _WB_RESOLVE_SUFFIXES
        rel = replace(normpath(candidate * suffix), "\\"=>"/")
        if !startswith(rel, "../") && rel != ".." && rel in files
            return rel
        end
    end
    return nothing
end
function _wb_find_imports(path::String, text::String)
    ext = lowercase(splitext(path)[2])
    deps = Tuple{String,String}[]
    if ext == ".jl"
        for m in eachmatch(r"(?m)^\s*(?:using|import)\s+([A-Za-z0-9_. ,]+)", text)
            for chunk in split(m.captures[1], ",")
                token = strip(split(strip(chunk), ":";limit=2)[1])
                isempty(token) || push!(deps, ("import",token))
            end
        end
        for m in eachmatch(r"include\s*\(\s*[\"']([^\"'\n]+)[\"']\s*\)", text)
            push!(deps, ("include",m.captures[1]))
        end
        for m in eachmatch(r"include\s*\(\s*joinpath\s*\(\s*@__DIR__\s*,\s*[\"']([^\"'\n]+)[\"']",text)
            push!(deps,("include",m.captures[1]))
        end
    elseif ext == ".py"
        for m in eachmatch(r"(?m)^\s*import\s+([A-Za-z0-9_., ]+)",text)
            for chunk in split(m.captures[1],",")
                name=strip(split(strip(chunk)," as ";limit=2)[1])
                isempty(name)||push!(deps,("import",name))
            end
        end
        for m in eachmatch(r"(?m)^\s*from\s+([.A-Za-z0-9_]+)\s+import\s+",text)
            push!(deps,("import",m.captures[1]))
        end
    elseif ext in (".js",".jsx",".ts",".tsx",".mjs",".cjs")
        for m in eachmatch(r"(?:import|export)\s+(?:[^\n'\";]*?\s+from\s+)?[\"']([^\"'\n]+)[\"']",text)
            push!(deps,("import",m.captures[1]))
        end
        for m in eachmatch(r"(?:require|import)\s*\(\s*[\"']([^\"'\n]+)[\"']\s*\)",text)
            push!(deps,("import",m.captures[1]))
        end
    elseif basename(path) == "package.json"
        try
            obj=JSON.parse(text)
            for section in ("dependencies","devDependencies","peerDependencies","optionalDependencies")
                block=get(obj,section,nothing)
                block isa AbstractDict || continue
                for key in keys(block)
                    push!(deps,("package",string(key)))
                end
            end
        catch
        end
    elseif basename(path) in ("Project.toml","Cargo.toml")
        in_deps = false
        for line in split(text,"\n")
            txt=strip(line)
            if startswith(txt,"[")
                in_deps=txt in ("[deps]","[dependencies]","[dev-dependencies]")
                continue
            end
            in_deps||continue
            mat=match(r"^([A-Za-z0-9_.-]+)\s*=",txt)
            mat===nothing||push!(deps,("package",mat.captures[1]))
        end
    end
    return unique(deps)
end
function _webula_scan_dependencies(root::String; max_bytes::Int=500_000)
    source_files=String[]
    oversized_files=String[]
    for (dir,dirs,fs) in walkdir(root)
        filter!(d -> !(d in _WB_EXCLUDED_DIRS),dirs)
        for f in fs
            ext=lowercase(splitext(f)[2])
            ext in _WB_CODE_EXTS || continue
            startswith(f,"ui.before-") && continue
            startswith(f,"BYTE.before-") && continue
            full=joinpath(dir,f)
            isfile(full) || continue
            if filesize(full)>max_bytes
                push!(oversized_files,replace(relpath(full,root),"\\"=>"/"))
                continue
            end
            push!(source_files,replace(relpath(full,root),"\\"=>"/"))
        end
    end
    sort!(source_files)
    files=Set(source_files)
    source_text=Dict{String,String}()
    julia_modules=Dict{String,String}()
    for rel in source_files
        try
            txt=read(joinpath(root,rel),String)
            source_text[rel]=txt
            if endswith(rel,".jl")
                for m in eachmatch(r"(?m)^\s*(?:baremodule|module)\s+([A-Za-z_][A-Za-z0-9_]*)",txt)
                    julia_modules[m.captures[1]]=rel
                end
            end
        catch
        end
    end
    relations=Dict{String,Any}[]
    ext_nodes=Dict{String,Any}[]
    outgoing=Dict{String,Any}()
    inbound=Dict{String,Vector{String}}()
    seen=Set{String}()
    ext_seen=Set{String}()
    unresolved=0
    internal=0
    for rel in source_files
        haskey(source_text,rel)||continue
        ext=lowercase(splitext(rel)[2])
        lang = ext == ".jl" ? "jl" : ext == ".py" ? "py" : "js"
        path_info=Dict{String,Any}("internal"=>String[],"external"=>String[],"unresolved"=>String[])
        for (kind,spec) in _wb_find_imports(rel,source_text[rel])
            target=_wb_resolve_import(rel,spec,files;language=lang,kind=kind,julia_modules=julia_modules)
            if target!==nothing && target != rel
                id="file:" * target
                push!(path_info["internal"],target)
                key=rel*"|"*id*"|"*kind
                if !(key in seen)
                    push!(seen,key)
                    push!(relations,Dict("source"=>"file:"*rel,"target"=>id,
                        "kind"=>kind,"spec"=>spec,"confidence"=>"resolved"))
                    push!(get!(inbound,target,String[]),rel)
                    internal+=1
                end
            elseif startswith(spec,".") || startswith(spec,"/") || kind=="include"
                unresolved+=1
                push!(path_info["unresolved"],spec)
            else
                dep=replace(spec,r"[^a-zA-Z0-9._@/\-+]"=>"")
                isempty(dep)&&continue
                if !(dep in ext_seen)
                    push!(ext_seen,dep)
                    push!(ext_nodes,Dict("id"=>"ext:"*dep,"name"=>dep,"type"=>"external",
                        "val"=>3,"path"=>dep))
                end
                push!(path_info["external"],dep)
                key=rel*"|ext:"*dep*"|"*kind
                if !(key in seen)
                    push!(seen,key)
                    push!(relations,Dict("source"=>"file:"*rel,"target"=>"ext:"*dep,
                        "kind"=>(kind == "package" ? "package" : "external"),"spec"=>spec,
                        "confidence"=>"import-declaration"))
                end
            end
        end
        outgoing[rel]=path_info
    end
    return Dict{String,Any}(
        "type"=>"builder_dependencies",
        "links"=>relations,
        "external_nodes"=>ext_nodes,
        "dependency_map"=>outgoing,
        "reverse_map"=>inbound,
        "stats"=>Dict("files_indexed"=>length(source_files),"files_parsed"=>length(source_text),
            "internal"=>internal,"external_packages"=>length(ext_nodes),
            "unresolved"=>unresolved,"total_links"=>length(relations),
            "oversized_skipped"=>length(oversized_files),
            "oversized_files"=>oversized_files),
    )
end
function _wb_manual_file(root::String)
    joinpath(root,"data","webula_manual_links.json")
end
function _wb_read_manual(root::String)
    path=_wb_manual_file(root)
    isfile(path)||return Dict{String,Any}[]
    try
        a=JSON.parsefile(path)
        return a isa AbstractVector ? a : Dict{String,Any}[]
    catch
        return Dict{String,Any}[]
    end
end
function _wb_validate_manual(a)
    a isa AbstractVector || return false
    length(a)<=250 || return false
    for edge in a
        edge isa AbstractDict || return false
        for k in ("source","target","kind")
            v=get(edge,k,nothing)
            v isa AbstractString || return false
            ncodeunits(v)<=270 || return false
            occursin(r"^[A-Za-z0-9_./:@+\-]+$",v)||return false
        end
        edge["kind"] in ("binds","feeds","related","calls","manual_dep") || return false
        edge["source"]!=edge["target"] || return false
    end
    return true
end
