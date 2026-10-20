"""
Called by BYTE.jl to verify a Fetch.ai payment on-chain.
Usage: python verify_fetch_payment.py <tx_hash> <expected_afet> <to_address>
Exits 0 = verified, 1 = not verified.
"""
import sys, json, urllib.request, urllib.error

def verify(tx_hash: str, expected_afet: int, to_address: str) -> bool:
    url = f"https://rest-fetchhub.fetch.ai/cosmos/tx/v1beta1/txs/{tx_hash}"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"ERROR: could not fetch tx: {e}", file=sys.stderr)
        return False

    # Check tx succeeded
    tx_resp = data.get("tx_response", {})
    if tx_resp.get("code", 1) != 0:
        print("FAIL: tx failed on-chain", file=sys.stderr)
        return False

    # Walk messages looking for a MsgSend to our address with enough afet
    tx_body = data.get("tx", {}).get("body", {})
    for msg in tx_body.get("messages", []):
        if msg.get("@type") != "/cosmos.bank.v1beta1.MsgSend":
            continue
        if msg.get("to_address", "").lower() != to_address.lower():
            continue
        for coin in msg.get("amount", []):
            if coin.get("denom") == "afet":
                sent = int(coin.get("amount", 0))
                if sent >= expected_afet:
                    print(f"OK: {sent} afet received", file=sys.stderr)
                    return True

    print("FAIL: no matching payment found in tx", file=sys.stderr)
    return False

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: verify_fetch_payment.py <tx_hash> <expected_afet> <to_address>")
        sys.exit(1)
    tx_hash       = sys.argv[1]
    expected_afet = int(sys.argv[2])
    to_address    = sys.argv[3]
    ok = verify(tx_hash, expected_afet, to_address)
    sys.exit(0 if ok else 1)
