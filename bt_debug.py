from substrateinterface import SubstrateInterface
import json
substrate = SubstrateInterface(url="wss://entrypoint-finney.opentensor.ai:443", type_registry_preset="substrate-node-template", use_remote_preset=True)
meta = substrate.get_metadata()
# Get SubtensorModule storage items
for i in range(len(meta.pallets)):
    p = meta.pallets[i]
    if p.name == "SubtensorModule":
        print(f"Pallet: {p.name}")
        for j in range(len(p.storage)):
            s = p.storage[j]
            print(f"  Storage: {s.name}")
