import asyncio
from uagents.network import get_almanac_contract
from uagents import Model

async def check_status():
    address = "agent1qvxe3nda67qhv6288y4j79eujjgtu8lkvduuhuunkxf00phqfxkzu8rpnz3"
    try:
        contract = get_almanac_contract()
        endpoints = contract.query_endpoints(address)
        return endpoints
    except Exception as e:
        return str(e)

import nest_asyncio
nest_asyncio.apply()
loop = asyncio.get_event_loop()
result = loop.run_until_complete(check_status())
print(result)
