"""
Stripe checkout + API key issuance (minimal, fast-to-ship).

If STRIPE_SECRET is not set, a stub response is returned so you can demo
without live billing. On successful session creation, you can mint an API key
and return it to the caller (email delivery can be plugged in later).
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from api_keys import create_api_key

try:
    import stripe
except Exception:  # pragma: no cover - stripe is optional for offline demos
    stripe = None

STRIPE_SECRET = os.environ.get("STRIPE_SECRET")
STRIPE_PRICE_FREE = os.environ.get("STRIPE_PRICE_FREE", "price_free_placeholder")
STRIPE_PRICE_INDIE = os.environ.get("STRIPE_PRICE_INDIE", "price_indie_placeholder")
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO", "price_pro_placeholder")


def _price_for_plan(plan: str) -> str:
    plan = (plan or "free").lower()
    if plan == "indie":
        return STRIPE_PRICE_INDIE
    if plan == "pro":
        return STRIPE_PRICE_PRO
    return STRIPE_PRICE_FREE


def create_checkout_session(plan: str, email: str | None = None) -> Dict[str, str]:
    plan = (plan or "free").lower()
    price_id = _price_for_plan(plan)

    if not stripe or not STRIPE_SECRET:
        # Offline stub
        key = create_api_key(plan=plan, email=email)
        return {
            "checkout_url": f"https://example.com/checkout-stub/{plan}",
            "api_key": key.api_key,
            "plan": plan,
            "mode": "stub",
        }

    stripe.api_key = STRIPE_SECRET
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=os.environ.get("STRIPE_SUCCESS_URL", "https://example.com/success?session_id={CHECKOUT_SESSION_ID}"),
        cancel_url=os.environ.get("STRIPE_CANCEL_URL", "https://example.com/cancel"),
        customer_email=email,
    )
    return {
        "checkout_url": session.url,
        "plan": plan,
        "mode": "live",
    }
