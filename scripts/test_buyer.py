import asyncio
import time
from uagents import Agent, Context, Model

# --- 1. Define the Message Models (Must match the Oracle) ---
class AlphaRequest(Model):
    agent_name: str

class AlphaResponse(Model):
    alpha_score: int
    market_summary: str
    payment_status: str

class PaymentRequired(Model):
    amount_fet: float
    wallet_address: str
    message: str

# --- 2. Initialize the Buyer Agent ---
# This agent doesn't need a real wallet for this test, just a random seed.
buyer = Agent(
    name="dumb-buyer-bot",
    seed="random_seed_for_buyer_bot_12345",
    port=8002,
    endpoint=["http://127.0.0.1:8002/submit"]
)

# The address of our ASI1 Oracle (We know this from the previous checks)
ORACLE_ADDRESS = "agent1qvxe3nda67qhv6288y4j79eujjgtu8lkvduuhuunkxf00phqfxkzu8rpnz3"

@buyer.on_event("startup")
async def startup_routine(ctx: Context):
    ctx.logger.info("💸 Buyer Bot Online! Looking for Alpha...")
    # Wait a few seconds for the Oracle to boot up, then send a request
    await asyncio.sleep(3)
    ctx.logger.info(f"Sending request to Oracle at {ORACLE_ADDRESS}...")
    await ctx.send(ORACLE_ADDRESS, AlphaRequest(agent_name="dumb-buyer-bot"))

@buyer.on_message(model=PaymentRequired)
async def handle_payment_demand(ctx: Context, sender: str, msg: PaymentRequired):
    ctx.logger.info(f"🚨 Oracle demanded payment!")
    ctx.logger.info(f"Message: {msg.message}")
    ctx.logger.info(f"Amount: {msg.amount_fet} FET")
    ctx.logger.info(f"Send to: {msg.wallet_address}")
    ctx.logger.info("I am too broke to pay this. Shutting down.")

@buyer.on_message(model=AlphaResponse)
async def handle_alpha_received(ctx: Context, sender: str, msg: AlphaResponse):
    ctx.logger.info(f"🤑 JACKPOT! Received Alpha!")
    ctx.logger.info(f"Score: {msg.alpha_score}")
    ctx.logger.info(f"Summary: {msg.market_summary}")

if __name__ == "__main__":
    buyer.run()
