using JLEngine
JLEngine.BYTE.dispatch("live_dashboard", Dict("port"=>8080))
println("Dashboard server started on http://localhost:8080")
while true
    sleep(1)
end