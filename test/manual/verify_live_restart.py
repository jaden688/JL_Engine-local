import sys
sys.stdout.reconfigure(encoding='utf-8')
import json,time,urllib.request,pathlib
from websockets.sync.client import connect
root = pathlib.Path(__file__).resolve().parents[2]
base = "http://127.0.0.1:8081"
def get(path):
    with urllib.request.urlopen(base+path,timeout=4) as f: return json.load(f)
def ready(seconds=100):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try: return get("/health")
        except Exception: time.sleep(1)
    raise RuntimeError("Engine did not become healthy")
if len(sys.argv)>1:
    before={'session_id':sys.argv[1]}
else:
    before=ready()
    print("Before restart:",before,flush=True)
    ws=connect("ws://127.0.0.1:8081",open_timeout=8)
    ws.send(json.dumps({"type":"restart_server"}))
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        m=json.loads(ws.recv(timeout=15))
        if m.get("type")=="tool":
            print("Restart acknowledgement:",m,flush=True)
            break
    ws.close()
end=time.monotonic()+120
after=None
while time.monotonic()<end:
    try:
        h=get("/health")
        if h["session_id"]!=before["session_id"]:
            after=h
            break
    except Exception: pass
    time.sleep(1)
if after is None: raise RuntimeError("Restart did not produce a new healthy session")
print("After restart:",after,flush=True)
with urllib.request.urlopen(base+"/api/models",timeout=30) as f:
    print("Models endpoint:",f.status,"bytes",len(f.read()),flush=True)
ws=connect("ws://127.0.0.1:8081",open_timeout=10)
ws.send(json.dumps({"type":"agent_change","agent":"Balthazar"}))
while True:
    m=json.loads(ws.recv(timeout=15))
    if m.get("type")=="agent_changed":
        assert m["agent"]=="Balthazar"
        print("Restored selection:",m,flush=True)
        break
ws.close()
state=get("/control/state")
assert state["active_agent"]=="Balthazar"
(root/"tmp/live-restart-browser-fix.json").write_text(json.dumps({"before":before,"after":after,"selected":state["active_agent"]},indent=2))
print("PASS: live restart, health, model listing, and Balthazar selection",flush=True)
