import os
from uagents import Agent, Context, Model
from dotenv import load_dotenv
from transformers import pipeline

load_dotenv()

SEED = os.getenv("TRADER_WALLET_KEY")

class OracleRequest(Model):
    query: str

class OracleResponse(Model):
    sentiment: str
    confidence: float
    fee_charged: str

# Initialize the agent
oracle_agent = Agent(
    name="quant_oracle",
    port=8000,
    seed=SEED,
    endpoint=["http://127.0.0.1:8000/submit"],
)

# Global variable to hold the model so we only load it once
sentiment_model = None

@oracle_agent.on_event("startup")
async def startup(ctx: Context):
    global sentiment_model
    ctx.logger.info(f"Starting up Quant Oracle Agent.")
    ctx.logger.info(f"Agent Address: {oracle_agent.address}")
    
    ctx.logger.info("Loading local financial sentiment model (DistilRoBERTa)...")
    try:
        sentiment_model = pipeline(
            "sentiment-analysis", 
            model="mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis"
        )
        ctx.logger.info("Model loaded successfully!")
    except Exception as e:
        ctx.logger.error(f"Failed to load model: {e}")

@oracle_agent.on_message(model=OracleRequest, replies=OracleResponse)
async def handle_request(ctx: Context, sender: str, msg: OracleRequest):
    ctx.logger.info(f"Received query from {sender}: {msg.query}")
    
    if sentiment_model is None:
        await ctx.send(sender, OracleResponse(
            sentiment="ERROR", 
            confidence=0.0, 
            fee_charged="0 FET"
        ))
        return

    # Run the local model
    result = sentiment_model(msg.query)[0]
    label = result['label']
    score = result['score']
    
    ctx.logger.info(f"Analysis complete: {label} ({score:.4f})")
    
    response = OracleResponse(
        sentiment=label,
        confidence=score,
        fee_charged="0.5 FET"
    )
    
    await ctx.send(sender, response)

if __name__ == "__main__":
    oracle_agent.run()
