# Tool Forge

## Purpose

Tool Forge creates small temporary tools that can be listed, run, deleted, or promoted into the core tool set.

It is a local operator feature within the JL Engine runtime.

## Runtime storage

From a source checkout, forged tools default to:

`src/tools_runtime/`

When installed into a non-writable package location, the runtime falls back to:

`~/.jl_engine/tools_runtime/`

These files are runtime state. They should be treated as ephemeral and should not be committed to the repository.

## Core operations

- create a temporary tool
- list current temporary tools
- run a temporary tool
- delete a temporary tool
- promote a stable tool into `src/jl_platform/core/tools/promoted/`

## API endpoints

- `POST /tools/forge/create`
- `GET /tools/forge/list`
- `POST /tools/forge/run`
- `POST /tools/forge/delete`
- `POST /tools/forge/promote`
- `POST /tools/forge/promote-last`

## Design notes

- the on-disk forge is intentionally persistent across runs until explicit deletion
- quest RAM tools are a separate lifecycle and can expire automatically
- promoted tools are the bridge from scratch runtime code to maintained core tooling

## Repository hygiene

- keep `src/tools_runtime/` ignored
- do not check in sample scratch tools from local experimentation
- document promoted tools in code, not by leaving temporary runtime files in version control
