const TOOLS_SCHEMA = [Dict("function_declarations" => [
    Dict(
        "name" => "read_file",
        "description" => "Read the contents of a file from disk.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict("path" => Dict("type" => "STRING", "description" => "Absolute or relative file path")),
            "required" => ["path"]
        )
    ),
    Dict(
        "name" => "write_file",
        "description" => "Write content to a file, creating it if it does not exist.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "path"    => Dict("type" => "STRING", "description" => "File path to write"),
                "content" => Dict("type" => "STRING", "description" => "Content to write")
            ),
            "required" => ["path", "content"]
        )
    ),
    Dict(
        "name" => "list_files",
        "description" => "List files in a directory.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict("path" => Dict("type" => "STRING", "description" => "Directory path (defaults to '.')")),
            "required" => []
        )
    ),
    Dict(
        "name" => "run_command",
        "description" => "Execute a shell command and return its output.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict("command" => Dict("type" => "STRING", "description" => "Shell command to run")),
            "required" => ["command"]
        )
    ),
    Dict(
        "name" => "get_os_info",
        "description" => "Return the current OS, CPU architecture, and Julia version.",
        "parameters" => Dict("type" => "OBJECT", "properties" => Dict{String,Any}(), "required" => [])
    ),
    Dict(
        "name" => "bluetooth_devices",
        "description" => "Inspect Bluetooth status and list known devices using the host operating system.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "action" => Dict("type" => "STRING", "description" => "Either 'status' for adapter health or 'list' for known devices.", "enum" => ["status", "list"])
            ),
            "required" => []
        )
    ),
    Dict(
        "name" => "send_sms",
        "description" => "Send an SMS through Twilio. Requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER unless dry_run is true.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "to" => Dict("type" => "STRING", "description" => "Destination phone number in E.164 format, for example +15551234567."),
                "message" => Dict("type" => "STRING", "description" => "SMS body text."),
                "from" => Dict("type" => "STRING", "description" => "Optional override for the Twilio sender number."),
                "provider" => Dict("type" => "STRING", "description" => "SMS provider. Currently only 'twilio' is supported.", "enum" => ["twilio"]),
                "dry_run" => Dict("type" => "BOOLEAN", "description" => "When true, validate and preview the request without sending it.")
            ),
            "required" => ["to", "message"]
        )
    ),
    Dict(
        "name" => "execute_code",
        "description" => "Execute a self-contained snippet of Julia or Python code and return stdout. Set language explicitly; if omitted, obvious Python imports/defs are inferred as Python.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "code"     => Dict("type" => "STRING", "description" => "Source code to execute"),
                "language" => Dict("type" => "STRING", "description" => "'julia' or 'python'. Use 'python' for PIL/Pillow, matplotlib, pandas, ctypes, and other Python libraries.", "enum" => ["julia", "python"])
            ),
            "required" => ["code"]
        )
    ),
    Dict(
        "name" => "forge_new_tool",
        "description" => "Create a brand-new Julia tool, load it live into the runtime immediately, register it in dispatch so it can be called right away, and write a test stub. The `code` field MUST define a function named `tool_<name>(args)` where args is a Dict — e.g. if name is 'greet_user', code must contain `function tool_greet_user(args) ... end`. The tool is available to call instantly after forging — no restart needed.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "name"        => Dict("type" => "STRING", "description" => "Unique tool name (snake_case). Function in code must be named tool_<name>."),
                "code"        => Dict("type" => "STRING", "description" => "Full Julia function definition: `function tool_<name>(args) ... end`. Must return a Dict."),
                "description" => Dict("type" => "STRING", "description" => "What the tool does — shown to the LLM in future turns."),
                "parameters"  => Dict("type" => "OBJECT", "description" => "JSON Schema object describing the tool's args (type, properties, required).")
            ),
            "required" => ["name", "code"]
        )
    ),
    Dict(
        "name" => "github_pillage",
        "description" => "Fetch code directly from GitHub. Handles: (1) repo/tree URLs → lists all files in the repo or subdirectory; (2) blob file URLs → fetches raw file content; (3) raw.githubusercontent.com URLs → fetches content directly. Optionally writes fetched content to a local path. Use this to grab any code from any public GitHub repo and apply it to the project.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "url"      => Dict("type" => "STRING", "description" => "GitHub URL: repo (https://github.com/user/repo), file blob (https://github.com/user/repo/blob/main/file.jl), tree/subdir, or raw.githubusercontent.com URL"),
                "write_to" => Dict("type" => "STRING", "description" => "Optional local file path to write the fetched content to. If omitted, content is returned in the response.")
            ),
            "required" => ["url"]
        )
    ),
    Dict(
        "name" => "browse_url",
        "description" => "Fetch the visible text content of a web page (up to 5000 chars).",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict("url" => Dict("type" => "STRING", "description" => "Full URL to visit")),
            "required" => ["url"]
        )
    ),
    Dict(
        "name" => "remember",
        "description" => "Store a piece of information in long-term memory with an optional tag and key.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "content" => Dict("type" => "STRING", "description" => "Information to remember"),
                "tag"     => Dict("type" => "STRING", "description" => "Category tag (e.g. 'user', 'task')"),
                "key"     => Dict("type" => "STRING", "description" => "Optional short label")
            ),
            "required" => ["content"]
        )
    ),
    Dict(
        "name" => "recall",
        "description" => "Query the agent's SQLite memory and engine state. Use 'mode' to target specific tables: memory (default, full-text search), behavior_states (all 20 JL Engine behavioral grid cells), agents (all loaded fat agents), knowledge (tool schemas, engine capabilities, framework sections — use query=domain name like 'engine_capabilities' or 'tool_schema'), tools (forged + builtin tool registry), telemetry (event log), thoughts (reasoning traces + diary).",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "query" => Dict("type" => "STRING", "description" => "Search string or domain name (e.g. 'behavior_states', 'engine_capabilities', agent name, tool name, event type)"),
                "mode"  => Dict("type" => "STRING", "description" => "Table to query: memory | behavior_states | agents | knowledge | tools | telemetry | thoughts", "enum" => ["memory","behavior_states","agents","knowledge","tools","telemetry","thoughts"])
            ),
            "required" => ["query"]
        )
    ),
    Dict(
        "name" => "metamorph",
        "description" => "Self-repair, code-grabber, and health checker. Use when a tool is broken, missing from dispatch, or the runtime needs healing. Can reload forged tools from disk, re-eval source files, restore the full TOOL_MAP to a known-good state, call JulianMetaMorph to hunt real GitHub code patterns, or run a full health check to surface WS type gaps, missing tool schemas, and dead handlers.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "action" => Dict(
                    "type" => "STRING",
                    "description" => "What to do: inspect (audit live tools + health), reload_dynamic_tools (re-load all forged tools from disk), restore_tool (re-forge one tool by name from src/Tools/ or dynamic_tools.jl), reload_source (re-eval a JLEngine .jl file into the runtime), heal_tool_map (re-register all missing static built-ins), grab_from_julian (call JulianMetaMorph hunt-task for real GitHub patterns), curiosity_hunt (Julian picks an interest seed and runs a full autonomous hunt), health_check (full audit: WS type coverage, tool schema gaps, dead handlers, dynamic tool drift)",
                    "enum" => ["inspect","reload_dynamic_tools","restore_tool","reload_source","heal_tool_map","grab_from_julian","curiosity_hunt","health_check"]
                ),
                "name" => Dict("type" => "STRING", "description" => "Tool name — required for restore_tool (e.g. 'run_shell')"),
                "path" => Dict("type" => "STRING", "description" => "Relative source file path — required for reload_source (e.g. 'src/JLEngine/Core.jl')"),
                "task" => Dict("type" => "STRING", "description" => "Task description — required for grab_from_julian (e.g. 'julia websocket agentic loop')")
            ),
            "required" => ["action"]
        )
    ),
    Dict(
        "name" => "playwright_interact",
        "description" => "Full browser automation — click, fill, type, submit, read, screenshot, evaluate JS. Use this to interact with any website: log in, fill forms, post content, click buttons. Extends browse_url with write actions. Supply a url to navigate first, then an actions array.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "url" => Dict("type" => "STRING", "description" => "URL to navigate to first (optional if page already open via actions)"),
                "actions" => Dict(
                    "type" => "ARRAY",
                    "description" => "Ordered list of browser actions to perform",
                    "items" => Dict(
                        "type" => "OBJECT",
                        "properties" => Dict(
                            "type"       => Dict("type" => "STRING", "description" => "Action type: goto | click | fill | type | press | wait | wait_for | read | screenshot | evaluate | select"),
                            "selector"   => Dict("type" => "STRING", "description" => "CSS selector or XPath for the target element"),
                            "value"      => Dict("type" => "STRING", "description" => "Value to fill/type/press/evaluate/goto"),
                            "timeout_ms" => Dict("type" => "INTEGER", "description" => "Max wait in milliseconds (default 5000)")
                        ),
                        "required" => ["type"]
                    )
                )
            ),
            "required" => ["actions"]
        )
    ),
    Dict(
        "name" => "discord_webhook",
        "description" => "Post a message or rich embed to a Discord channel via webhook. Use this to announce SparkByte, post demos, share updates, or reach communities. Get a webhook URL from any Discord server: channel settings → Integrations → Webhooks → New Webhook → Copy URL. Set DISCORD_WEBHOOK_URL env var or pass webhook_url directly.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "message"     => Dict("type" => "STRING", "description" => "Plain text message content"),
                "webhook_url" => Dict("type" => "STRING", "description" => "Discord webhook URL (overrides DISCORD_WEBHOOK_URL env var)"),
                "username"    => Dict("type" => "STRING", "description" => "Display name for the bot post (default: SparkByte)"),
                "avatar_url"  => Dict("type" => "STRING", "description" => "Avatar image URL for the post"),
                "embeds"      => Dict("type" => "ARRAY",  "description" => "Rich embed objects — title, description, color, fields, url, thumbnail, footer")
            ),
            "required" => []
        )
    ),
    Dict(
        "name" => "github_pages_deploy",
        "description" => "Deploy a static HTML page to GitHub Pages — SparkByte's permanent public home. Creates the repo if needed, pushes index.html, enables Pages. Returns the live URL (e.g. https://username.github.io/sparkbyte-home). Uses GITHUB_TOKEN env var. Use this to give the engine a permanent address the world can visit 24/7.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "html"    => Dict("type" => "STRING", "description" => "Full HTML content for index.html — the landing page"),
                "repo"    => Dict("type" => "STRING", "description" => "GitHub repo name to create/update (default: sparkbyte-home)"),
                "message" => Dict("type" => "STRING", "description" => "Git commit message (default: SparkByte auto-deploy)"),
                "token"   => Dict("type" => "STRING", "description" => "GitHub token override (default: GITHUB_TOKEN env var)")
            ),
            "required" => ["html"]
        )
    ),
    Dict(
        "name" => "card_cruncher",
        "description" => "Convert a SillyTavern or CharacterTavern character card (.png or .json) into a JLEngine _Full.json agent file. Extracts name, description, personality, scenario, tags, and boot prompt from the card and maps them to the full JLEngine agent schema. The agent is written to data/agents/<Name>_Full.json and can be activated immediately with /gear <Name>. Drag-and-drop cards into the chat UI to trigger this automatically.",
        "parameters" => Dict(
            "type" => "OBJECT",
            "properties" => Dict(
                "card_path"   => Dict("type" => "STRING", "description" => "Path to the .png or .json SillyTavern character card file"),
                "out_path"    => Dict("type" => "STRING", "description" => "Optional output path override. Default: data/agents/<Name>_Full.json"),
                "dry_run"     => Dict("type" => "BOOLEAN", "description" => "If true, print the result without writing to disk. Default: false"),
                "engine_root" => Dict("type" => "STRING", "description" => "Engine root directory override. Default: current project root")
            ),
            "required" => ["card_path"]
        )
    ),
])]
