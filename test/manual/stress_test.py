import asyncio
import json
import uuid
import websockets

async def test_engine():
    uri = "ws://127.0.0.1:8081"
    try:
        async with websockets.connect(uri) as websocket:
            # Switch to Ultimate agent first
            await websocket.send(json.dumps({
                "type": "command",
                "text": "/gear Ultimate"
            }))
            
            # Send a complex technical task
            task = "I need a tool that can gather system telemetry (CPU load, disk usage, memory). Use the Swarm Forge to build `tool_sys_report` collaboratively."
            
            print(f"🚀 Sending Task: {task}")
            await websocket.send(json.dumps({
                "type": "chat",
                "text": task,
                "id": str(uuid.uuid4())
            }))

            while True:
                try:
                    # Increase timeout to give the engine time to think and forge
                    msg = await asyncio.wait_for(websocket.recv(), timeout=60)
                    data = json.loads(msg)
                    
                    mtype = data.get("type")
                    if mtype == "thinking":
                        print(f"🧠 [THOUGHT]: {data.get('text')}")
                    elif mtype == "signal":
                        print(f"📡 [SIGNAL]: {data.get('metrics')}")
                    elif mtype == "behavior":
                        print(f"🎭 [BEHAVIOR]: {data.get('state')} (Gait: {data.get('gait')})")
                    elif mtype == "spark":
                        print(f"✨ [SPARKBYTE]: {data.get('text')}")
                        break
                    elif mtype == "error":
                        print(f"❌ [ERROR]: {data.get('text')}")
                        break
                    elif mtype == "forge_start":
                        print(f"🛠️ [FORGE]: Starting to forge `{data.get('name')}`...")
                    elif mtype == "forge_done":
                        print(f"✅ [FORGE]: `{data.get('name')}` completed.")
                except asyncio.TimeoutError:
                    print("... Still thinking ...")
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    asyncio.run(test_engine())
