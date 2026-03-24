## Serial tool bridge examples

Tool payloads are routed through the Open Interpreter bridge:

```json
{"mode": "tool", "tool": "serial", "payload": {"action": "status", "port": "COM4"}}
```

```json
{"mode": "tool", "tool": "serial", "payload": {"action": "connect", "port": "COM4", "baudrate": 115200}}
```

```json
{"mode": "tool", "tool": "serial", "payload": {"action": "send", "port": "COM4", "baudrate": 115200, "line": "M114"}}
```

```json
{"mode": "tool", "tool": "serial", "payload": {"action": "disconnect", "port": "COM4"}}
```
