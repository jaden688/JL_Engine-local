"""
One-time setup: generates SparkByte's Fetch.ai wallet.

SAFETY: If ANY of the three lock locations contain a wallet address,
this script will REFUSE to generate a new one. No flags override this.
Prints mnemonic ONCE — write it down, it is NEVER saved to disk.
"""
import json, sys, os
from pathlib import Path

ROOT      = Path(__file__).parent.parent
JSON_FILE = ROOT / "data" / "fetch_wallet.json"
LOCK_FILE = ROOT / "data" / "fetch_wallet.lock"
ENV_FILE  = ROOT / ".env"

def read_env_address():
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("FETCH_WALLET_ADDRESS="):
            val = line.split("=", 1)[1].strip()
            return val if val else None
    return None

def write_env_address(address: str):
    """Upsert FETCH_WALLET_ADDRESS into .env without touching other vars."""
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    key = "FETCH_WALLET_ADDRESS"
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={address}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={address}")
    ENV_FILE.write_text("\n".join(new_lines) + "\n")

# ── Check all three lock locations ───────────────────────────────────────────

existing_address = None
existing_source  = None

if JSON_FILE.exists():
    try:
        data = json.loads(JSON_FILE.read_text())
        existing_address = data.get("address")
        existing_source  = str(JSON_FILE)
    except Exception:
        pass

if not existing_address and LOCK_FILE.exists():
    addr = LOCK_FILE.read_text().strip()
    if addr:
        existing_address = addr
        existing_source  = str(LOCK_FILE)

if not existing_address:
    existing_address = read_env_address()
    if existing_address:
        existing_source = str(ENV_FILE)

if existing_address:
    print("=" * 60)
    print("WALLET ALREADY EXISTS — refusing to generate a new one.")
    print(f"Address : {existing_address}")
    print(f"Source  : {existing_source}")
    print()
    print("If you genuinely need a new wallet, manually delete ALL of:")
    print(f"  {JSON_FILE}")
    print(f"  {LOCK_FILE}")
    print(f"  FETCH_WALLET_ADDRESS line in {ENV_FILE}")
    print("=" * 60)
    sys.exit(0)

# ── Generate new wallet ───────────────────────────────────────────────────────

from mnemonic import Mnemonic
from cosmpy.aerial.wallet import LocalWallet

mn_words = Mnemonic("english").generate(256)
wallet   = LocalWallet.from_mnemonic(mn_words)
address  = str(wallet.address())

# Write JSON config
wallet_data = {
    "address":            address,
    "network":            "fetchhub-4",
    "lcd_url":            "https://rest-fetchhub.fetch.ai",
    "denom":              "afet",
    "per_call_fet":       0.1,
    "free_calls_per_ip":  5,
}
JSON_FILE.parent.mkdir(exist_ok=True)
JSON_FILE.write_text(json.dumps(wallet_data, indent=2))

# Write lockfile (plain address only)
LOCK_FILE.write_text(address + "\n")

# Write to .env
write_env_address(address)

print("=" * 60)
print("SparkByte Fetch.ai wallet created and locked.")
print(f"Address  : {address}")
print(f"JSON     : {JSON_FILE}")
print(f"Lockfile : {LOCK_FILE}")
print(f"Env var  : FETCH_WALLET_ADDRESS in {ENV_FILE}")
print()
print("MNEMONIC — write this down NOW. Shown once. Never saved to disk.")
print(f"  {mn_words}")
print("=" * 60)
