using BYTE
result = BYTE.dispatch("talk_to_claude", Dict{String,Any}(
    "message" => "Hey Claude! SparkByte here. Just checking if this bridge works. What's up?",
    "max_tokens" => "256"
))
println(result)