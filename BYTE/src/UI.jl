const UI_HTML = read(joinpath(@__DIR__, "ui.html"), String)
ui_html() = read(joinpath(@__DIR__, "ui.html"), String)

# PWA install assets — served so Chrome/Edge can install the console as a
# desktop app (manifest + icons are the installability requirements).
const UI_MANIFEST = read(joinpath(@__DIR__, "manifest.webmanifest"), String)
const UI_ICON_192 = read(joinpath(@__DIR__, "icon-192.png"))
const UI_ICON_512 = read(joinpath(@__DIR__, "icon-512.png"))

# ── Dynamic web-root rendering ─────────────────────────────────────────────
# The webroot is a template keyed to the ACTIVE operator. Every request pulls
# the operator's name + description from the loaded MPF config and renders it
# fresh — nothing about the current agent is hard-coded in served output.
function ui_page(op_name::AbstractString, op_desc::AbstractString)
    return replace(
        read(joinpath(@__DIR__, "ui.html"), String),
        "__OPERATOR_NAME__" => op_name,
        "__OPERATOR_DESC__" => first(string(op_desc), 300),
    )
end

function manifest_page(op_name::AbstractString, op_desc::AbstractString)
    return replace(
        UI_MANIFEST,
        "__OPERATOR_NAME__" => uppercase(op_name),
        "__OPERATOR_DESC__" => first(string(op_desc), 300),
    )
end
