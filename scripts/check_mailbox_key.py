import os
from dotenv import load_dotenv

load_dotenv()
key = os.environ.get("AGENTVERSE_MAILBOX_KEY", "")
print(f"Mailbox Key found: {'Yes' if key else 'No'}")
if key:
    print(f"Key starts with: {key[:5]}...")
