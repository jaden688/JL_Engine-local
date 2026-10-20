using JLEngine
# Start dashboard on port 8080
JLEngine.BYTE.dispatch("live_dashboard", Dict("port"=>8080))
println("Dashboard started. Opening browser...")
# Forge a test tool to generate an event
forge_res = JLEngine.BYTE.dispatch("forge_new_tool", Dict(
    "name"=>"hello_world",
    "code"=>"function tool_hello_world(args)\n    Dict(\"result\"=>\"Hello, gremlin!\")\nend",
    "description"=>"A simple hello world tool",
    "parameters"=>Dict("type"=>"OBJECT","properties"=>Dict(),"required"=>String[])
))
println("Forge result: ", forge_res)
# Keep process alive so dashboard stays up
while true
    sleep(1)
end
