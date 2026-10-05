"""Channel3 product search client.

API shape confirmed against https://docs.trychannel3.com/api-reference/v1/search
  POST https://api.trychannel3.com/v1/search
  Header: x-api-key: <CHANNEL3_API_KEY>
"""
import os

import requests

BASE_URL = "https://api.trychannel3.com"
TIMEOUT_SECONDS = 20


class Channel3Error(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def search(query, min_price=None, max_price=None, limit=10, user_id=None):
    """Search Channel3 and return a list of normalized, listening-friendly products."""
    api_key = os.getenv("CHANNEL3_API_KEY")
    if not api_key:
        raise Channel3Error("CHANNEL3_API_KEY is not set", status=500)

    body = {
        "query": query,
        "limit": max(1, min(int(limit), 30)),
        "filters": {},
        # PayPal sandbox charges in USD, so keep prices in USD.
        "config": {"country": "US", "currency": "USD"},
    }
    price = {}
    if min_price is not None:
        price["min_price"] = float(min_price)
    if max_price is not None:
        price["max_price"] = float(max_price)
    if price:
        body["filters"]["price"] = price

    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    if user_id:
        headers["x-user-id"] = user_id

    try:
        resp = requests.post(f"{BASE_URL}/v1/search", json=body, headers=headers, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise Channel3Error(f"Channel3 request failed: {e}")

    if resp.status_code == 401:
        raise Channel3Error("Channel3 rejected the API key", status=502)
    if resp.status_code == 402:
        raise Channel3Error("Channel3 credits exhausted", status=502)
    if not resp.ok:
        raise Channel3Error(f"Channel3 error {resp.status_code}: {resp.text[:300]}")

    products = [normalize(p) for p in resp.json().get("products", [])]
    # Drop anything we can't price or buy, and re-check the cap ourselves.
    products = [p for p in products if p["price"] is not None]
    if max_price is not None:
        products = [p for p in products if p["price"] <= float(max_price)]
    return products


def _best_offer(offers):
    in_stock = [o for o in offers if o.get("availability") == "InStock" and o.get("price")]
    pool = in_stock or [o for o in offers if o.get("price")]
    if not pool:
        return None
    return min(pool, key=lambda o: o["price"].get("price") or float("inf"))


def _sizes(variants):
    """Return in-stock size labels, if the product has a size option."""
    if not variants:
        return []
    for option in variants.get("options") or []:
        if "size" in (option.get("name") or "").lower():
            return [
                v["label"]
                for v in option.get("values") or []
                if v.get("exists", True) and v.get("available") != "OutOfStock"
            ]
    return []


def normalize(p):
    """Flatten a Channel3 product into the fields the agent actually needs."""
    offer = _best_offer(p.get("offers") or [])
    main_image = next((i for i in p.get("images") or [] if i.get("is_main_image")), None)
    description = (p.get("description") or "").strip()
    return {
        "id": p.get("id"),
        "title": p.get("title"),
        "brand": ", ".join(b["name"] for b in p.get("brands") or [] if b.get("name")) or None,
        "price": offer["price"].get("price") if offer else None,
        "currency": offer["price"].get("currency") if offer else None,
        "retailer": offer.get("domain") if offer else None,
        "url": offer.get("url") if offer else None,
        "in_stock": bool(offer and offer.get("availability") == "InStock"),
        "materials": p.get("materials") or [],
        "key_features": (p.get("key_features") or [])[:5],
        "sizes_in_stock": _sizes(p.get("variants")),
        "category": (p.get("category") or {}).get("title"),
        "description": description[:400],
        "image_alt": main_image.get("alt_text") if main_image else None,
        "image_url": main_image.get("url") if main_image else None,
    }
