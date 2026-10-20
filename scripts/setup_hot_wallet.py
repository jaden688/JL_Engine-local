"""
Generates SparkByte's hot wallet — used for signing transactions,
paying gas, and registering on Agentverse.

The mnemonic IS saved to disk (data/hot_wallet.key) so SparkByte
can sign autonomously. Keep this machine secure.

This wallet is for SPENDING. Earnings go to the main payment wallet.
"""
import json, sys
from pathlib import Path
from mnemonic import Mnemonic
from cosmpy.aerial.wallet import LocalWallet

ROOT      = Path(__file__).parent.parent
JSON_FILE = ROOT / "data" / "hot_wallet.json"
KEY_FILE  = ROOT / "data" / "hot_wallet.key"   # mnemonic lives here

if JSON_FILE.exists() or KEY_FILE.exists():
    print("=" * 60)
    print("HOT WALLET ALREADY EXISTS — refusing to overwrite.")
    if JSON_FILE.exists():
        data = json.loads(JSON_FILE.read_text())
        print(f"Address : {data.get('address')}")
    print(f"Key file: {KEY_FILE}")
    print("=" * 60)
    sys.exit(0)

mn_words = Mnemonic("english").generate(256)
wallet   = LocalWallet.from_mnemonic(mn_words)
address  = str(wallet.address())

JSON_FILE.parent.mkdir(exist_ok=True)

JSON_FILE.write_text(json.dumps({
    "address":  address,
    "network":  "fetchhub-4",
    "lcd_url":  "https://rest-fetchhub.fetch.ai",
    "denom":    "afet",
    "purpose":  "hot_spending",
}, indent=2))

KEY_FILE.write_text(mn_words + "\n")

print("=" * 60)
print("SparkByte hot wallet created.")
print(f"Address  : {address}")
print(f"Key file : {KEY_FILE}  ← keep this machine secure")
print()
print("Next: send a small amount of FET to that address to fund it.")
print("Earnings still route to your main wallet.")
print("=" * 60)
