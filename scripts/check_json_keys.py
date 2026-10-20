import os
import json

# Check if it's in any json files in root
for file in os.listdir('.'):
    if file.endswith('.json'):
        try:
            with open(file, 'r') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if 'mailbox' in k.lower() or 'agentverse' in k.lower():
                            print(f"Found in {file}: {k}")
        except:
            pass
