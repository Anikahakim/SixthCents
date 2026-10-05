import json
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import anthropic  # noqa: E402

import agent  # noqa: E402
import channel3  # noqa: E402  (needs env loaded first)
import confirm  # noqa: E402
import paypal  # noqa: E402
import store  # noqa: E402

app = Flask(__name__)
store.init()

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5173").rstrip("/")
MAX_SPENDING_CAP = 10000


@app.get("/api/health")
def health():
    # Report which keys are present without ever exposing their values.
    keys = [
        "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_BASE_URL", "PAYPAL_WEBHOOK_ID",
        "CHANNEL3_API_KEY", "ANTHROPIC_API_KEY",
    ]
    return jsonify(ok=True, configured={k: bool(os.getenv(k)) for k in keys})


@app.post("/api/search")
def search():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify(error="query is required"), 400
    try:
        products = channel3.search(
            query,
            min_price=data.get("min_price"),
            max_price=data.get("max_price"),
            limit=data.get("limit", 10),
        )
    except channel3.Channel3Error as e:
        return jsonify(error=str(e)), e.status
    except (TypeError, ValueError):
        return jsonify(error="min_price, max_price and limit must be numbers"), 400
    return jsonify(products=products)


@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify(error="message is required"), 400
    try:
        return jsonify(agent.chat(data.get("session_id"), message))
    except anthropic.APIStatusError as e:
        app.logger.error("Claude API error %s: %s", e.status_code, e.message)
        return jsonify(error="The assistant is unavailable right now. Please try again."), 502
    except anthropic.APIConnectionError:
        return jsonify(error="Could not reach the assistant. Check your connection."), 502


@app.post("/api/confirm")
def confirm_purchase():
    """Reply to a pending purchase. Charges only on an explicit yes with a valid token."""
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify(error="message is required"), 400
    try:
        body, status = confirm.handle(data.get("session_id"), data.get("confirmation_token"), message)
    except anthropic.APIStatusError as e:
        app.logger.error("Claude API error %s: %s", e.status_code, e.message)
        return jsonify(error="The assistant is unavailable right now. Please try again."), 502
    except anthropic.APIConnectionError:
        return jsonify(error="Could not reach the assistant. Check your connection."), 502
    return jsonify(body), status


# ---- Account setup: link PayPal (Vault) and set a spending cap ----

def _account_json():
    user = store.get_user()
    return {
        "linked": bool(user["vault_id"]),
        "payer_email": user["payer_email"],
        "spending_cap": user["spending_cap"],
        "sandbox": paypal.is_sandbox(),
    }


@app.get("/api/account")
def account():
    return jsonify(_account_json())


@app.put("/api/account/cap")
def set_cap():
    data = request.get_json(silent=True) or {}
    try:
        cap = round(float(data.get("spending_cap")), 2)
    except (TypeError, ValueError):
        return jsonify(error="Spending limit must be a number of dollars."), 400
    if not 0 < cap <= MAX_SPENDING_CAP:
        return jsonify(error=f"Spending limit must be between $1 and ${MAX_SPENDING_CAP}."), 400
    store.update_user(spending_cap=cap)
    return jsonify(_account_json())


@app.post("/api/paypal/setup")
def paypal_setup():
    """Start linking: returns PayPal's approval URL for the browser to visit."""
    try:
        result = paypal.create_setup_token(
            return_url=f"{APP_BASE_URL}/?paypal=return",
            cancel_url=f"{APP_BASE_URL}/?paypal=cancel",
        )
    except paypal.PayPalError as e:
        app.logger.error("PayPal setup failed: %s %s", e, e.details)
        return jsonify(error=f"Couldn't start PayPal linking: {e}"), e.status
    store.update_user(pending_setup_token=result["setup_token"])
    return jsonify(approve_url=result["approve_url"])


@app.post("/api/paypal/complete")
def paypal_complete():
    """After the buyer approves at PayPal, exchange the setup token for a saved wallet (vault_id)."""
    user = store.get_user()
    if not user["pending_setup_token"]:
        return jsonify(error="No PayPal linking in progress."), 400
    try:
        saved = paypal.create_payment_token(user["pending_setup_token"])
    except paypal.PayPalError as e:
        app.logger.error("PayPal vault failed: %s %s", e, e.details)
        return jsonify(error=f"PayPal linking didn't finish: {e}"), e.status
    store.update_user(
        vault_id=saved["vault_id"],
        paypal_customer_id=saved["customer_id"],
        payer_email=saved["payer_email"],
        pending_setup_token=None,
    )
    return jsonify(_account_json())


@app.post("/api/paypal/unlink")
def paypal_unlink():
    user = store.get_user()
    if user["vault_id"]:
        try:
            paypal.delete_payment_token(user["vault_id"])
        except paypal.PayPalError as e:
            app.logger.warning("PayPal token delete failed (clearing locally anyway): %s", e)
    store.update_user(vault_id=None, paypal_customer_id=None, payer_email=None, pending_setup_token=None)
    return jsonify(_account_json())


# ---- Orders and webhooks ----

@app.get("/api/orders/<order_id>")
def order_status(order_id):
    order = store.get_order(order_id)
    if not order:
        return jsonify(error="Order not found"), 404
    keys = ("id", "title", "size", "amount", "currency", "status", "webhook_confirmed", "paypal_order_id")
    return jsonify({k: order[k] for k in keys})


@app.post("/api/paypal/webhook")
def paypal_webhook():
    try:
        event = json.loads(request.get_data())
    except ValueError:
        return jsonify(error="bad json"), 400
    try:
        if not paypal.verify_webhook(request.headers, event):
            app.logger.warning("Rejected unverified PayPal webhook %s", event.get("id"))
            return jsonify(error="signature verification failed"), 400
    except paypal.PayPalError as e:
        app.logger.error("Webhook verification error: %s", e)
        return jsonify(error="verification unavailable"), 503  # PayPal will retry

    kind = event.get("event_type", "")
    resource = event.get("resource") or {}
    app.logger.info("PayPal webhook %s %s", kind, resource.get("id"))

    if kind.startswith("PAYMENT.CAPTURE."):
        paypal_order_id = ((resource.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
        order = (paypal_order_id and store.find_order_by_paypal_id(paypal_order_id)) or store.find_order_by_capture_id(resource.get("id"))
        if not order:
            return jsonify(error="unknown order, retry later"), 503  # may race our own DB write
        status = {
            "PAYMENT.CAPTURE.COMPLETED": "CAPTURE_CONFIRMED",
            "PAYMENT.CAPTURE.DENIED": "DENIED",
            "PAYMENT.CAPTURE.PENDING": "PENDING",
        }.get(kind)
        if status:
            store.update_order(order["id"], status=status, capture_id=resource.get("id"), webhook_confirmed=1)
    elif kind == "VAULT.PAYMENT-TOKEN.DELETED":
        if store.get_user()["vault_id"] == resource.get("id"):
            store.update_user(vault_id=None, paypal_customer_id=None, payer_email=None)

    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", 5001)))
