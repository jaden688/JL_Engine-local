import urllib.request, json

addr = "fetch1hrxg30uaqzwhzkkwr4hqmxsp0vsc7w9nndwyu5"
url  = f"https://rest-fetchhub.fetch.ai/cosmos/bank/v1beta1/balances/{addr}"
req  = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

with urllib.request.urlopen(req, timeout=10) as r:
    data = json.loads(r.read())

balances = data.get("balances", [])
if not balances:
    print("0 FET — not arrived yet or wallet empty")
for b in balances:
    denom  = b["denom"]
    amount = int(b["amount"])
    if denom == "afet":
        fet = amount / 1_000_000_000_000_000_000
        print(f"Balance: {fet:.4f} FET")
    else:
        print(f"{denom}: {amount}")
