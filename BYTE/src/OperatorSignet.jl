using Dates, JSON, SHA

const _SIGNET_SCHEMA = "jl-operator-receipt.v1"
const _SIGNET_ALG = "hmac-sha256"
const _SIGNET_HASH_TAG = "jl688"

function _signet_secret()
    secret = strip(get(ENV, "JL_OPERATOR_SIGNING_SECRET", ""))
    isempty(secret) && (secret = strip(get(ENV, "SPARKBYTE_OPERATOR_SIGNING_SECRET", "")))
    return secret
end

function _signet_hex(bytes)
    return bytes2hex(Vector{UInt8}(bytes))
end

function _signet_sha256_hex(value)
    return _SIGNET_HASH_TAG * ":" * bytes2hex(sha256(String(value)))
end

function _signet_default_run_id()
    if isdefined(@__MODULE__, :_session_id)
        value = getfield(@__MODULE__, :_session_id)
        return value isa Base.RefValue ? string(value[]) : string(value)
    end
    return string(round(Int, datetime2unix(now())))
end

function _signet_hmac_sha256(key::AbstractString, message::AbstractString)
    block_size = 64
    key_bytes = Vector{UInt8}(codeunits(String(key)))
    if length(key_bytes) > block_size
        key_bytes = Vector{UInt8}(sha256(key_bytes))
    end
    if length(key_bytes) < block_size
        append!(key_bytes, fill(UInt8(0), block_size - length(key_bytes)))
    end
    outer = UInt8[xor(b, 0x5c) for b in key_bytes]
    inner = UInt8[xor(b, 0x36) for b in key_bytes]
    msg_bytes = Vector{UInt8}(codeunits(String(message)))
    inner_hash = sha256(vcat(inner, msg_bytes))
    return sha256(vcat(outer, Vector{UInt8}(inner_hash)))
end

function canonical_json(value)::String
    if value === nothing
        return "null"
    elseif value isa Bool
        return value ? "true" : "false"
    elseif value isa Integer
        return string(value)
    elseif value isa AbstractFloat
        isfinite(value) || error("Cannot canonicalize non-finite float")
        return JSON.json(value)
    elseif value isa AbstractString
        return JSON.json(String(value))
    elseif value isa AbstractDict
        pairs_sorted = sort([(string(k), v) for (k, v) in pairs(value)]; by=first)
        return "{" * join([JSON.json(k) * ":" * canonical_json(v) for (k, v) in pairs_sorted], ",") * "}"
    elseif value isa AbstractVector || value isa Tuple
        return "[" * join([canonical_json(item) for item in value], ",") * "]"
    else
        return canonical_json(string(value))
    end
end

function operator_receipt(; operator::AbstractString, action::AbstractString, tool::AbstractString="",
        args=nothing, result=nothing, loop_iter::Integer=0, elapsed_ms::Integer=0,
        run_id::AbstractString="", parent_receipt::AbstractString="")
    ts = string(now(UTC))
    payload = Dict{String,Any}(
        "schema" => _SIGNET_SCHEMA,
        "operator" => string(operator),
        "action" => string(action),
        "tool" => string(tool),
        "loop_iter" => Int(loop_iter),
        "elapsed_ms" => Int(elapsed_ms),
        "timestamp" => ts,
        "run_id" => isempty(run_id) ? _signet_default_run_id() : string(run_id),
        "args_hash" => args === nothing ? "" : _signet_sha256_hex(canonical_json(args)),
        "result_hash" => result === nothing ? "" : _signet_sha256_hex(canonical_json(result)),
        "parent_receipt" => string(parent_receipt),
    )
    canonical = canonical_json(payload)
    secret = _signet_secret()
    if isempty(secret)
        payload["signature_alg"] = "none"
        payload["signature"] = ""
        payload["signature_status"] = "unsigned:no JL_OPERATOR_SIGNING_SECRET"
    else
        payload["signature_alg"] = _SIGNET_ALG
        payload["signature"] = _signet_hex(_signet_hmac_sha256(secret, canonical))
        payload["signature_status"] = "signed"
    end
    payload["canonical_hash"] = _signet_sha256_hex(canonical)
    return payload
end

function verify_operator_receipt(receipt::AbstractDict; secret::AbstractString=_signet_secret())
    payload = Dict{String,Any}(string(k) => v for (k, v) in pairs(receipt))
    signature = string(get(payload, "signature", ""))
    alg = string(get(payload, "signature_alg", ""))
    isempty(signature) && return false
    alg == _SIGNET_ALG || return false
    isempty(secret) && return false
    delete!(payload, "signature")
    delete!(payload, "signature_alg")
    delete!(payload, "signature_status")
    delete!(payload, "canonical_hash")
    expected = _signet_hex(_signet_hmac_sha256(secret, canonical_json(payload)))
    return lowercase(signature) == lowercase(expected)
end

function operator_receipt_headers(receipt::AbstractDict)
    return Pair{String,String}[
        "X-JL-Operator-ID" => string(get(receipt, "operator", "")),
        "X-JL-Operator-Run" => string(get(receipt, "run_id", "")),
        "X-JL-Operator-Action" => string(get(receipt, "action", "")),
        "X-JL-Receipt-Schema" => string(get(receipt, "schema", _SIGNET_SCHEMA)),
        "X-JL-Operator-Signature" => string(get(receipt, "signature_alg", "none")) * ":" * string(get(receipt, "signature", "")),
    ]
end
