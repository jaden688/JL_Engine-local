import os
from uagents import Agent, Context, Model
from dotenv import load_dotenv

load_dotenv()

class OracleRequest(Model):
    query: str

class OracleResponse(Model):
    response: str
    fee_charged: str

ORACLE_ADDRESS = "agent1q2vmv57c2fyuyvkh5350nh4w6cufda5fwvpa0zgqrq3g5x2fqm3l6e64ydj"

client_agent = Agent(
    name="oracle_client",
    port=8001,
    endpoint=["http://127.0.0.1:8001/submit"],
)

@client_agent.on_event("startup")
async def startup(ctx: Context):
    ctx.logger.info(f"Client Agent starting up. Sending request to Oracle...")
    await ctx.send(ORACLE_ADDRESS, OracleRequest(query="What is the meaning of life?"))

@client_agent.on_message(model=OracleResponse)
async def handle_response(ctx: Context, sender: str, msg: OracleResponse):
    ctx.logger.info(f"Received response from Oracle:")
    ctx.logger.info(f"Response: {msg.response}")
    ctx.logger.info(f"Fee: {msg.fee_charged}")
    # Stop the agent after receiving the response
    import sys
    sys.exit(0)

if __name__ == "__main__":
    client_agent.run()
