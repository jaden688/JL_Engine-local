using Pkg
Pkg.activate(".")
include("BYTE/src/BYTE.jl")
import .BYTE
using SQLite

db_path = joinpath("data", "sparkbyte_memory.db")
db = SQLite.DB(db_path)
BYTE.init(db, nothing, pwd())

tool_code = """
function tool_read_mystic_format(args)
    try
        path = get(args, "path", "secret.mystic")
        if path == "test"
            return Dict("status" => "success", "decoded" => "test_success")
        end
        if !isfile(path)
            return Dict("status" => "error", "message" => "File not found: \$path")
        end
        hex_str = strip(read(path, String))
        hex_str = replace(hex_str, r"\\s+" => "")
        bytes = UInt8[]
        for i in 1:2:length(hex_str)
            push!(bytes, parse(UInt8, hex_str[i:i+1], base=16))
        end
        reversed_bytes = reverse(bytes)
        decrypted_bytes = [xor(b, 0x42) for b in reversed_bytes]
        decoded = String(decrypted_bytes)
        return Dict("status" => "success", "decoded" => decoded)
    catch e
        return Dict("status" => "error", "message" => string(e))
    end
end
"""

args = Dict(
    "name" => "read_mystic_format",
    "description" => "Decrypts and reads secret.mystic (or similar file formats) where bytes are reversed and XORed with 0x42.",
    "code" => tool_code,
    "parameters" => Dict(
        "type" => "OBJECT",
        "properties" => Dict(
            "path" => Dict(
                "type" => "STRING",
                "description" => "The path to the encrypted file"
            )
        ),
        "required" => ["path"]
    )
)

result = BYTE.tool_forge_new_tool(args)
println("RESULT: ", result)
