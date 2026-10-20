import os
from uagents import Agent, Context, Model
from uagents.setup import fund_agent_if_low
from dotenv import load_dotenv

load_dotenv()

# The same mnemonic we used to derive the agent's wallet
SEED = os.getenv("TRADER_WALLET_KEY")

# Define the message models
class OracleRequest(Model):
    query: str

class OracleResponse(Model):
    response: str
    fee_charged: str

# Initialize the agent
oracle_agent = Agent(
    name="sparkbyte_oracle",
    port=8000,
    seed=SEED,
    endpoint=["http://127.0.0.1:8000/submit"],
)

@oracle_agent.on_event("startup")
async def startup(ctx: Context):
    ctx.logger.info(f"Starting up SparkByte Oracle Agent.")
    ctx.logger.info(f"Agent Address: {oracle_agent.address}")
    ctx.logger.info(f"Wallet Address: {oracle_agent.wallet.address()}")
    
    # Check balance
    balance = ctx.ledger.query_bank_balance(oracle_agent.wallet.address())
    ctx.logger.info(f"Current Balance: {balance} afet")

@oracle_agent.on_message(model=OracleRequest, replies=OracleResponse)
async def handle_request(ctx: Context, sender: str, msg: OracleRequest):
    ctx.logger.info(f"Received query from {sender}: {msg.query}")
    
    # Here we would normally call OpenAI/Gemini. For now, a placeholder response.
    # We will upgrade this to a real AI call next.
    analysis = f"Analysis for '{msg.query}': Market conditions are volatile. Proceed with caution."
    
    response = OracleResponse(
        response=analysis,
        fee_charged="0.1 FET (Payment verification pending implementation)"
    )
    
    await ctx.send(sender, response)

if __name__ == "__main__":
    oracle_agent.run()
