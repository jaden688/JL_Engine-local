function tool_run_shell(args::Dict)
  # ---- validate input -------------------------------------------------
  cmd = get(args, "command", nothing)
  if cmd === nothing || !(cmd isa String)
    return Dict("success"=>false, "error"=>"’command’ must be a string")
  end

  # ---- run the command ------------------------------------------------
  success  = false
  output   = ""
  err_msg  = ""
  try
    raw_output = tool_run_command(Dict("command"=>cmd))
    success = true
    output  = raw_output
  catch e
    err_msg = string(e)
  end

  # ---- audit log ------------------------------------------------------
  log_line = "$(Dates.now()) | CMD: $cmd | SUCCESS: $success\n"
  try
    open("run_shell.log", "a") do io
      write(io, log_line)
    end
  catch
    # logging failure is non-fatal
  end

  # ---- build response --------------------------------------------------
  resp = Dict("success"=>success, "output"=>output)
  !success && (resp["error"] = err_msg)
  return resp
end
