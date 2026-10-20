import os
import sys
from dotenv import load_dotenv
from uagents_core.utils.registration import (
    register_chat_agent,
    RegistrationRequestCredentials,
)

# Load environment variables from .env
load_dotenv()

MNEMONIC = os.getenv("TRADER_WALLET_KEY")
AGENTVERSE_KEY = os.getenv("AGENTVERSE_API_KEY")

print("Registering SparkByte-1 with Agentverse and creating handle...")

if not AGENTVERSE_KEY:
    print("ERROR: AGENTVERSE_API_KEY environment variable is not set. Please configure it in your .env file.")
    sys.exit(1)

if not MNEMONIC:
    print("ERROR: TRADER_WALLET_KEY environment variable is not set. Please configure it in your .env file.")
    sys.exit(1)

try:
    register_chat_agent(
        "sparkbyte", # This becomes the handle!
        "https://5c13-2001-56a-7dfc-c300-a867-9d88-aecc-f0b7.ngrok-free.app/submit",
        active=True,
        credentials=RegistrationRequestCredentials(
            agentverse_api_key=AGENTVERSE_KEY,
            agent_seed_phrase=MNEMONIC,
        ),
    )
    print("Registration complete! Handle created and agent is officially on Agentverse!")
except Exception as e:
    print(f"Uh oh, something went wrong: {e}")
