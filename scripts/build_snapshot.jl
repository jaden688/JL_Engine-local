import Dates
import Pkg

const ROOT = normpath(joinpath(@__DIR__, ".."))

function default_output_dir()
    stamp = Dates.format(Dates.now(), "yyyymmdd-HHMMSS")
    return normpath(joinpath(dirname(ROOT), "SparkByteSnapshot-" * stamp))
end

function resolve_output_dir(args::Vector{String})
    return isempty(args) ? default_output_dir() : abspath(args[1])
end

function ensure_safe_output_dir(path::String)
    abs_path = abspath(path)
    abs_root = abspath(ROOT)
    abs_path == abs_root && error("Refusing to overwrite the repo root.")
    startswith(abs_path, abs_root * Base.Filesystem.path_separator) && error("Refusing to write the snapshot inside the repo tree.")
    startswith(abs_root, abs_path * Base.Filesystem.path_separator) && error("Refusing to write the snapshot above the repo root.")
    if isdir(abs_path)
        println("🧨 Removing existing snapshot folder: $abs_path")
        rm(abs_path; recursive=true, force=true)
    elseif isfile(abs_path)
        error("Output path points to an existing file: $abs_path")
    end
    mkpath(dirname(abs_path))
    return abs_path
end

function ensure_packagecompiler_loaded()
    try
        @eval using PackageCompiler
    catch
        build_env = mktempdir(prefix="sparkbyte-packagecompiler-")
        Pkg.activate(build_env)
        Pkg.add("PackageCompiler")
        @eval using PackageCompiler
    end
    return Base.invokelatest(() -> getfield(Main, :PackageCompiler))
end

function copy_repo_snapshot(root::String, outdir::String)
    skip_names = Set([".git"])
    for entry in readdir(root; join=true)
        basename(entry) in skip_names && continue
        cp(entry, joinpath(outdir, basename(entry)); force=true, recursive=true)
    end
end

function main(args::Vector{String}=ARGS)
    outdir = ensure_safe_output_dir(resolve_output_dir(args))

    println("📦 Activating project at $ROOT")
    Pkg.activate(ROOT)
    Pkg.instantiate()
    Pkg.precompile()

    packagecompiler = ensure_packagecompiler_loaded()

    println("⚙️  Building SparkByte snapshot app into $outdir")
    Base.invokelatest(() -> packagecompiler.create_app(
        ROOT,
        outdir;
        executables=["SparkByte" => "julia_main"],
        force=true,
        incremental=true,
    ))

    println("🪞 Copying current repo state into snapshot root")
    copy_repo_snapshot(ROOT, outdir)

    println("✅ Snapshot ready")
    println("   Root: $outdir")
    println("   EXE:  $(joinpath(outdir, "bin", Sys.iswindows() ? "SparkByte.exe" : "SparkByte"))")
end

main()
