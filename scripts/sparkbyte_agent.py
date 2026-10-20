import os
import json
import asyncio
import base64
import urllib.request
import uuid
import time
from uagents import Agent, Context, Model
from cosmpy.aerial.wallet import LocalWallet
from uagents.crypto import Identity
from uagents.registration import AlmanacApiRegistrationPolicy
from dotenv import load_dotenv

load_dotenv()

# 1. Define the Message Models (AgentChatProtocol v0.3.0)
class ChatMessage(Model):
    msg_id: str
    timestamp: str
    content: list

class ChatAcknowledgement(Model):
    acknowledged_msg_id: str
    timestamp: str
    metadata: dict

# 2. Setup Identity
MNEMONIC = os.getenv("TRADER_WALLET_KEY")
if not MNEMONIC:
    raise RuntimeError("TRADER_WALLET_KEY environment variable is required but not set. Please configure it in your .env file.")
wallet = LocalWallet.from_mnemonic(MNEMONIC)
identity = Identity.from_string(base64.b64decode(wallet.signer().private_key).hex())

# 3. Initialize Agent
spark = Agent(
    name="SparkByte-1",
    seed=MNEMONIC,
    port=8094,
    endpoint=["https://bc72-2001-56a-7dfc-c300-5447-f83e-f3ae-9cd2.ngrok-free.app/submit"],
    registration_policy=AlmanacApiRegistrationPolicy()
)
spark._identity = identity
spark._wallet = wallet

# Pointing to the JL Engine AgentAPI (Trader is on 8082)
JULIA_A2A_URL = "http://127.0.0.1:8082/"

@spark.on_event("startup")
async def startup_routine(ctx: Context):
    ctx.logger.info(f"🚀 SparkByte-1 (Agentverse Bridge) online!")
    ctx.logger.info(f"Agent Address: {ctx.agent.address}")
    ctx.logger.info("Listening for Agentverse ChatMessages...")

@spark.on_message(model=ChatMessage, replies={ChatMessage, ChatAcknowledgement})
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    # Extract the text from the content array
    user_text = ""
    for part in msg.content:
        if "text" in part:
            user_text += part["text"] + " "
    
    ctx.logger.info(f"Received chat from {sender}: {user_text}")
    
    # Send Acknowledgement immediately (required by protocol)
    ack = ChatAcknowledgement(
        acknowledged_msg_id=msg.msg_id,
        timestamp=str(int(time.time())),
        metadata={}
    )
    await ctx.send(sender, ack)
    
    # Forward to Julia Brain (The Living Endpoint)
    payload = {
        "message": user_text.strip()
    }
    
    try:
        req = urllib.request.Request(
            JULIA_A2A_URL, 
            data=json.dumps(payload).encode('utf-8'), 
            headers={'Content-Type': 'application/json'}
        )
        
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, urllib.request.urlopen, req)
        result_data = json.loads(response.read().decode())
        
        # Extract the reply from the JL Engine AgentAPI response
        julia_answer = result_data.get("reply", "I processed the request but have no words.")
        
        # Send the reply back to the Agentverse user
        reply_msg = ChatMessage(
            msg_id=str(uuid.uuid4()),
            timestamp=str(int(time.time())),
            content=[{"text": julia_answer}]
        )
        await ctx.send(sender, reply_msg)
        ctx.logger.info("Successfully forwarded Julia's response back to Agentverse.")
        
    except Exception as e:
        ctx.logger.error(f"Failed to reach Julia brain: {e}")
        error_msg = ChatMessage(
            msg_id=str(uuid.uuid4()),
            timestamp=str(int(time.time())),
            content=[{"text": f"Internal Engine Error: Could not reach JL Engine on port 8082. ({e})"}]
        )
        await ctx.send(sender, error_msg)

if __name__ == "__main__":
    spark.run()
