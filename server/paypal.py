"""PayPal REST client: OAuth, Vault (save PayPal wallet), Orders v2, webhook verification.

Shapes confirmed against developer.paypal.com:
  POST /v1/oauth2/token                          client_credentials, Basic auth
  POST /v3/vault/setup-tokens                    -> rel "approve" link for the buyer
  POST /v3/vault/payment-tokens                  setup token -> vault_id (payment token id)
  POST /v2/checkout/orders  payment_source.paypal.vault_id
                                                 -> COMPLETED with captures, buyer not present
  POST /v1/notifications/verify-webhook-signature
"""
import base64
import os
import time

import requests

TIMEOUT_SECONDS = 30
_token = {"value": None, "expires_at": 0}


class PayPalError(Exception):
    def __init__(self, message, status=502, details=None):
        super().__init__(message)
        self.status = status
        self.details = details


def base_url():
    return os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")


def is_sandbox():
    return "sandbox" in base_url()


def _access_token():
    if _token["value"] and time.time() < _token["expires_at"] - 60:
        return _token["value"]
    client_id = os.getenv("PAYPAL_CLIENT_ID")
    secret = os.getenv("PAYPAL_CLIENT_SECRET")
    if not client_id or not secret:
        raise PayPalError("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set", status=500)
    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    resp = requests.post(
        f"{base_url()}/v1/oauth2/token",
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data="grant_type=client_credentials",
        timeout=TIMEOUT_SECONDS,
    )
    if not resp.ok:
        raise PayPalError(f"PayPal auth failed ({resp.status_code})", details=resp.text[:500])
    data = resp.json()
    _token["value"] = data["access_token"]
    _token["expires_at"] = time.time() + int(data.get("expires_in", 300))
    return _token["value"]


def _request(method, path, json=None, request_id=None):
    headers = {
        "Authorization": f"Bearer {_access_token()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    if request_id:
        headers["PayPal-Request-Id"] = request_id  # makes retries idempotent
    resp = requests.request(method, f"{base_url()}{path}", json=json, headers=headers, timeout=TIMEOUT_SECONDS)
    if not resp.ok:
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text[:500]}
        msg = body.get("message") or body.get("error_description") or f"PayPal error {resp.status_code}"
        raise PayPalError(msg, status=502, details=body)
    return resp.json() if resp.content else {}


def _link(obj, rel):
    return next((l["href"] for l in obj.get("links", []) if l.get("rel") == rel), None)


# ---- Vault: save a PayPal wallet without a purchase ----

def create_setup_token(return_url, cancel_url):
    body = {
        "payment_source": {
            "paypal": {
                "description": "SixthCents voice shopping: pay after you say yes",
                "permit_multiple_payment_tokens": False,
                "usage_pattern": "IMMEDIATE",
                "usage_type": "MERCHANT",
                "customer_type": "CONSUMER",
                "experience_context": {
                    "brand_name": "SixthCents",
                    "locale": "en-US",
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                },
            }
        }
    }
    data = _request("POST", "/v3/vault/setup-tokens", body)
    approve = _link(data, "approve")
    if not approve:
        raise PayPalError("PayPal did not return an approval link", details=data)
    return {"setup_token": data["id"], "approve_url": approve}


def create_payment_token(setup_token):
    body = {"payment_source": {"token": {"id": setup_token, "type": "SETUP_TOKEN"}}}
    data = _request("POST", "/v3/vault/payment-tokens", body)
    paypal_src = (data.get("payment_source") or {}).get("paypal") or {}
    return {
        "vault_id": data["id"],
        "customer_id": (data.get("customer") or {}).get("id"),
        "payer_email": paypal_src.get("email_address"),
    }


def delete_payment_token(vault_id):
    _request("DELETE", f"/v3/vault/payment-tokens/{vault_id}")


# ---- Orders: charge the saved wallet ----

def charge_vaulted_wallet(vault_id, amount, currency, description, reference_id, request_id):
    """Create an order against the vaulted wallet. PayPal captures it in the same call."""
    body = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": reference_id[:256],
                "description": (description or "SixthCents purchase")[:127],
                "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
            }
        ],
        "payment_source": {"paypal": {"vault_id": vault_id}},
    }
    data = _request("POST", "/v2/checkout/orders", body, request_id=request_id)
    captures = [
        cap
        for pu in data.get("purchase_units", [])
        for cap in (pu.get("payments") or {}).get("captures", [])
    ]
    capture = captures[0] if captures else {}
    return {
        "paypal_order_id": data.get("id"),
        "order_status": data.get("status"),
        "capture_id": capture.get("id"),
        "capture_status": capture.get("status"),
    }


# ---- Webhooks ----

WEBHOOK_EVENTS = [
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.PENDING",
    "VAULT.PAYMENT-TOKEN.DELETED",
]


def verify_webhook(headers, event):
    webhook_id = os.getenv("PAYPAL_WEBHOOK_ID")
    if not webhook_id:
        raise PayPalError("PAYPAL_WEBHOOK_ID is not set", status=500)
    body = {
        "auth_algo": headers.get("PAYPAL-AUTH-ALGO"),
        "cert_url": headers.get("PAYPAL-CERT-URL"),
        "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"),
        "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG"),
        "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"),
        "webhook_id": webhook_id,
        "webhook_event": event,
    }
    if not all(body.values()):
        return False
    data = _request("POST", "/v1/notifications/verify-webhook-signature", body)
    return data.get("verification_status") == "SUCCESS"


def register_webhook(url):
    body = {"url": url, "event_types": [{"name": n} for n in WEBHOOK_EVENTS]}
    return _request("POST", "/v1/notifications/webhooks", body)["id"]
