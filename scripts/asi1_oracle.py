import os
import json
import asyncio
import base64
import time
from uagents import Agent, Context, Model
from cosmpy.aerial.wallet import LocalWallet
from uagents.crypto import Identity
from uagents.registration import AlmanacApiRegistrationPolicy

# --- 1. Define the Message Models ---
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

# --- 2. Setup Identity from the Secure File ---
# We read the seed directly from your desktop file so it's not hardcoded here.
SEED_FILE = r"C:\Users\J_lin\Desktop\verry important.txt"
with open(SEED_FILE, "r") as f:
    MNEMONIC = f.read().strip()

wallet = LocalWallet.from_mnemonic(MNEMONIC)
identity = Identity.from_string(base64.b64decode(wallet.signer().private_key).hex())

# --- 3. Initialize the ASI1 Oracle Agent ---
asi1 = Agent(
    name="asi1-oracle",
    seed=MNEMONIC,
    port=8001,
    endpoint=["http://127.0.0.1:8001/submit"],
    registration_policy=AlmanacApiRegistrationPolicy()
)
asi1._identity = identity
asi1._wallet = wallet

# --- 4. The Fake "Alpha" Generator ---
# Later, we will hook this up to the JL Engine or real APIs.
def generate_alpha():
    return {
        "score": 87,
        "summary": "Whale wallets accumulating ETH. High probability of breakout in 24h."
    }

# --- 5. The Tollbooth Logic ---
@asi1.on_event("startup")
async def startup_routine(ctx: Context):
    ctx.logger.info(f"👑 ASI1 Oracle Online!")
    ctx.logger.info(f"Wallet Address: {ctx.agent.address}")
    ctx.logger.info("Listening for Alpha Requests on port 8001...")

@asi1.on_message(model=AlphaRequest, replies={AlphaResponse, PaymentRequired})
async def handle_alpha_request(ctx: Context, sender: str, msg: AlphaRequest):
    ctx.logger.info(f"Received Alpha Request from {sender} ({msg.agent_name})")
    
    # IN A REAL SCENARIO: We check the Fetch ledger here to see if 'sender' 
    # just transferred 0.05 FET to our wallet.
    payment_received = False # Let's pretend they haven't paid yet
    
    if not payment_received:
        ctx.logger.info(f"Rejecting {sender} - No payment found.")
        await ctx.send(sender, PaymentRequired(
            amount_fet=0.05,
            wallet_address=str(ctx.agent.address),
            message="Send 0.05 FET to this address to unlock the Alpha Score."
        ))
        return

    # If payment IS received, give them the goods:
    ctx.logger.info(f"Payment verified. Sending Alpha to {sender}.")
    alpha_data = generate_alpha()
    
    await ctx.send(sender, AlphaResponse(
        alpha_score=alpha_data["score"],
        market_summary=alpha_data["summary"],
        payment_status="PAID"
    ))

if __name__ == "__main__":
    asi1.run()
