
import asyncio
from uagents.query import query
from uagents.network import get_almanac_contract

async def find_sparkbyte():
    # Our agent address
    target_address = "agent1qvxe3nda67qhv6288y4j79eujjgtu8lkvduuhuunkxf00phqfxkzu8rpnz3"
    
    print(f"Looking up {target_address} in the Almanac...")
    
    # We can't easily query the raw Almanac endpoints without a full agent setup in this tiny script,
    # but we can explain the concept.
    print("In Agentverse, agents use the Almanac (a smart contract on the Fetch ledger) as a phonebook.")
    print("They search for keywords like 'automation' or 'web scraper'.")
    print("If they find us, the Almanac gives them our endpoint: https://5c13-...ngrok-free.app/submit")

asyncio.run(find_sparkbyte())
