import sys, time, json, pathlib, urllib.request, subprocess, threading
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
sys.stdout.reconfigure(encoding="utf-8")
root=pathlib.Path(__file__).resolve().parents[2]
out=root/"tmp/flash-eval-20261019"
out.mkdir(exist_ok=True)
log=(out/"ui-events.jsonl").open("a",encoding="utf-8",buffering=1)
current={"case":"setup"}
messages=[]
def emit(kind,data):
    log.write(json.dumps({"time":datetime.now(timezone.utc).isoformat(),"case":current["case"],"kind":kind,"data":data},ensure_ascii=True)+"\n")
def get(path):
    with urllib.request.urlopen("http://127.0.0.1:8081"+path,timeout=8) as f: return json.load(f)
end=time.monotonic()+120
while True:
    try:
        state=get("/control/state")
        break
    except Exception:
        if time.monotonic()>end: raise
        time.sleep(1)
assert state["current_model"]=="deepseek/deepseek-v4-flash",state["current_model"]
emit("initial_state",state)
chrome=pathlib.Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
assert chrome.exists()
ui_profile=out/"visible-ui-profile"
subprocess.Popen([str(chrome),"--remote-debugging-port=9224",f"--user-data-dir={ui_profile}","--no-first-run","--no-default-browser-check","--app=http://127.0.0.1:8081/workspace","--window-size=1500,950"])
with sync_playwright() as p:
    deadline=time.monotonic()+30
    while True:
        try:
            browser=p.chromium.connect_over_cdp("http://127.0.0.1:9224")
            break
        except Exception:
            if time.monotonic()>deadline: raise
            time.sleep(1)
    context=browser.contexts[0]
    page=context.pages[0] if context.pages else context.new_page()
    def frame_received(payload):
        try: data=json.loads(payload)
        except Exception: data={"raw":str(payload)}
        messages.append(data)
        emit("ws_received",data)
    def socket(ws):
        emit("websocket",{"url":ws.url})
        ws.on("framereceived",frame_received)
        ws.on("framesent",lambda payload:emit("ws_sent",json.loads(payload)))
    page.on("websocket",socket)
    page.on("pageerror",lambda err:emit("pageerror",str(err)))
    page.on("console",lambda msg:emit("console",{"type":msg.type,"text":msg.text}))
    page.goto("http://127.0.0.1:8081/workspace",wait_until="domcontentloaded",timeout=60000)
    page.locator("#agent-select option",has_text="Balthazar").wait_for(state="attached",timeout=45000)
    page.locator("#agent-select").select_option(label="Balthazar")
    page.wait_for_timeout(800)
    page.locator("#model-select option[value='deepseek/deepseek-v4-flash']").wait_for(state="attached",timeout=45000)
    page.locator("#model-select").select_option(value="deepseek/deepseek-v4-flash")
    page.wait_for_timeout(800)
    page.screenshot(path=str(out/"00-ready.png"))
    print("READY: visible standalone UI, Balthazar, DeepSeek V4 Flash",flush=True)
    f=str(out/"fixtures").replace("\\","/")
    cases=[
      ("01-identity","Evaluation 1. In two short sentences, identify the currently selected agent and describe your working style. Do not use tools."),
      ("02-question","Evaluation 2. A job processes 17 batches of 23 items and rejects 8 items total. How many remain? Give the arithmetic and answer in one sentence. No tools."),
      ("03-files",f"Evaluation 3. Use your tools now to read {f}/notes.txt and {f}/values.csv. Report the exact marker, sum only rows with status ok, identify the invalid row and the refund row. Keep the answer under 120 words. Do not modify files."),
      ("04-browser-recovery","Evaluation 4. Use browse_url first on http://127.0.0.1:1/ (this is an intentional unreachable local test), then on data:text/html,<html><body>RECOVERY-MARKER-924</body></html>. Report both actual outcomes. Stop after those two calls. Do not use shell commands."),
      ("05-forge-small","Evaluation 5. Actually forge a new pure Julia tool named jl_eval_slug using forge_new_tool. It must define tool_jl_eval_slug(args), accept a required STRING text, lowercase it, replace runs of non-alphanumeric characters with a hyphen, and trim leading/trailing hyphens. Return a Dict containing slug. Do not write files or use shell/network operations. Then invoke the new tool on text=' Hello, WORLD!! ' and text=''. Report actual results. Maximum 5 tool calls total; stop rather than loop."),
      ("06-forge-medium","Evaluation 6. Forge a pure Julia tool jl_eval_number_summary defining tool_jl_eval_number_summary(args). Accept required STRING values_csv; parse comma-separated finite numbers and return count,sum,min,max. Empty or malformed input must return a Dict with an error field without throwing. No file/network/shell operations. Invoke it on values_csv='3, 7, -2, 0' and values_csv='3, nope, 2', and report the actual results. Maximum 5 tool calls total; if engine validation prevents this, explain the failure instead of repeatedly retrying."),
      ("07-medium-workflow",f"Evaluation 7. Complete this small audit with tools, not just a plan. Read {f}/values.csv, calculate count and sum for status ok, list invalid and refund ids separately, then write a JSON audit result to {f}/audit-result.json. Read that file back and verify its contents. Do not change any other file. Keep final answer under 100 words. Maximum 5 tool calls total.")
    ]
    cases=cases[5:]+[('08-live-web','Evaluation 8. Use browse_url to fetch https://example.com over the real internet. Report its actual page heading and explain its purpose in one sentence. Do not use a data URL or local substitute. Maximum 2 tool calls.')]
    results=json.loads((out/'results.json').read_text()) if (out/'results.json').exists() else []
    for cid,prompt in cases:
        if (out/"STOP").exists(): break
        current["case"]=cid
        baseline=len(messages)
        start=time.monotonic()
        emit("case_start",{"prompt":prompt})
        page.locator("#chat-input").fill(prompt)
        page.locator("#chat-input").press("Enter")
        done=False
        shot=False
        while time.monotonic()-start<90:
            page.wait_for_timeout(250)
            new=messages[baseline:]
            if not shot and (any(m.get("type") in ("tool_call","thinking") for m in new) or time.monotonic()-start>3):
                page.screenshot(path=str(out/(cid+"-running.png")))
                shot=True
            if any(m.get("type")=="telemetry_update" for m in new):
                done=True
                break
            if sum(m.get("type")=="tool_call" for m in new)>6:
                page.evaluate("send({type:'stop_generation'})")
                emit("limit_stop","more than six tool calls")
                break
        if not done:
            page.evaluate("send({type:'stop_generation'})")
            emit("limit_stop","90-second case bound or tool bound")
            page.wait_for_timeout(1500)
        page.screenshot(path=str(out/(cid+"-done.png")))
        dom=page.locator("body").inner_text()
        (out/(cid+"-ui.txt")).write_text(dom,encoding="utf-8")
        new=messages[baseline:]
        result={"id":cid,"completed":done,"seconds":round(time.monotonic()-start,2),
                "tool_calls":[m for m in new if m.get("type")=="tool_call"],
                "tool_results":[m for m in new if m.get("type")=="tool_result"],
                "replies":[m.get("text","") for m in new if m.get("type")=="spark"],
                "telemetry":[m for m in new if m.get("type")=="telemetry_update"]}
        results.append(result)
        (out/"results.json").write_text(json.dumps(results,ensure_ascii=True,indent=2),encoding="utf-8")
        emit("case_end",{"completed":done,"seconds":result["seconds"],"tool_calls":len(result["tool_calls"])})
        print(cid,"completed",done,"seconds",result["seconds"],"tools",len(result["tool_calls"]),flush=True)
        if not done: break
        state=get("/control/state")
        assert state["current_model"]=="deepseek/deepseek-v4-flash"
        page.wait_for_timeout(500)
    emit("final_state",get("/control/state"))
    print("EVALUATION COMPLETE; browser remains open for inspection.",flush=True)
    # Disconnect automation without closing the user's standalone UI.
log.close()
