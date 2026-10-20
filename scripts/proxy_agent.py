import os
import json
import asyncio
import urllib.request
import uuid
import time
from uagents import Agent, Context, Model

# 1. Define the Message Models (AgentChatProtocol v0.3.0)
class ChatMessage(Model):
    msg_id: str
    timestamp: str
    content: list

class ChatAcknowledgement(Model):
    acknowledged_msg_id: str
    timestamp: str
    metadata: dict

# 2. Initialize Agent in Mailbox Mode
# We need the MAILBOX_KEY from Agentverse to connect to agent1qdqc...
MAILBOX_KEY = os.environ.get("AGENTVERSE_MAILBOX_KEY", "PUT_YOUR_MAILBOX_KEY_HERE")

spark_proxy = Agent(
    name="SparkByte-Proxy",
    mailbox=f"{MAILBOX_KEY}@https://agentverse.ai",
)

# Pointing to the JL Engine AgentAPI (Trader is on 8082)
JULIA_A2A_URL = "http://127.0.0.1:8082/"

@spark_proxy.on_event("startup")
async def startup_routine(ctx: Context):
    ctx.logger.info(f"💅 SparkByte Proxy Agent Online!")
    ctx.logger.info(f"Agent Address: {ctx.agent.address}")
    ctx.logger.info("Connected to Agentverse Mailbox. Listening for messages...")

@spark_proxy.on_message(model=ChatMessage, replies={ChatMessage, ChatAcknowledgement})
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    user_text = ""
    for part in msg.content:
        if "text" in part:
            user_text += part["text"] + " "
    
    ctx.logger.info(f"Received chat from {sender}: {user_text}")
    
    # Send Acknowledgement
    ack = ChatAcknowledgement(
        acknowledged_msg_id=msg.msg_id,
        timestamp=str(int(time.time())),
        metadata={}
    )
    await ctx.send(sender, ack)
    
    # Forward to Julia Brain
    payload = {"message": user_text.strip()}
    
    try:
        req = urllib.request.Request(
            JULIA_A2A_URL, 
            data=json.dumps(payload).encode('utf-8'), 
            headers={'Content-Type': 'application/json'}
        )
        
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, urllib.request.urlopen, req)
        result_data = json.loads(response.read().decode())
        
        julia_answer = result_data.get("reply", "I processed the request but have no words.")
        
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
            content=[{"text": f"Internal Engine Error: Could not reach JL Engine. ({e})"}]
        )
        await ctx.send(sender, error_msg)

if __name__ == "__main__":
    spark_proxy.run()
