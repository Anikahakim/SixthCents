"""The only code path that charges money. Called by the server, never by the LLM."""
import sqlite3
import uuid

import paypal
import store


class CheckoutError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def place_order(confirmation_token, product_id, title, size, amount, currency, user_id=store.DEMO_USER):
    """Re-check the cap and charge the user's vaulted PayPal wallet once per confirmation token."""
    user = store.get_user(user_id)
    if not user or not user["vault_id"]:
        raise CheckoutError("PayPal isn't linked yet. Link PayPal in setup first.")
    if currency != "USD":
        raise CheckoutError("Only US dollar purchases are supported.")
    cap = user["spending_cap"]
    if cap is None:
        raise CheckoutError("Set a spending limit in setup before buying.")
    if amount <= 0 or amount > cap:
        raise CheckoutError(f"${amount:.2f} is over your spending limit of ${cap:.2f}.")

    order_id = uuid.uuid4().hex
    try:
        store.create_order(order_id, user_id, confirmation_token, product_id, title, size, amount, currency)
    except sqlite3.IntegrityError:
        raise CheckoutError("This purchase was already submitted.", status=409)

    description = f"{title} (size {size})" if size else title
    try:
        result = paypal.charge_vaulted_wallet(
            vault_id=user["vault_id"],
            amount=amount,
            currency=currency,
            description=description,
            reference_id=order_id,
            request_id=order_id,
        )
    except paypal.PayPalError as e:
        store.update_order(order_id, status="FAILED")
        raise CheckoutError(f"PayPal declined the payment: {e}", status=402)

    status = "COMPLETED" if result["capture_status"] == "COMPLETED" else (result["capture_status"] or result["order_status"] or "FAILED")
    store.update_order(order_id, paypal_order_id=result["paypal_order_id"], capture_id=result["capture_id"], status=status)
    return store.get_order(order_id)
