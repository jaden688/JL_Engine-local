def format_output(core_output):
    payload = core_output.payload
    return {"echo": payload.get("text"), "trace_id": core_output.trace_id}
