from uagents.network import get_almanac_contract
contract = get_almanac_contract()
address = "agent1qvxe3nda67qhv6288y4j79eujjgtu8lkvduuhuunkxf00phqfxkzu8rpnz3"
print("Registered:", contract.is_registered(address))
print("Endpoints:", contract.get_endpoints(address))
