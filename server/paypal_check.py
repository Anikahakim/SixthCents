"""PayPal sandbox helper.

  python paypal_check.py                      check credentials and linked-wallet status
  python paypal_check.py register-webhook URL subscribe URL (must be public https) to our events
  python paypal_check.py test-charge          charge $1.00 to the linked wallet (sandbox only)
"""
import os
import secrets
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import checkout  # noqa: E402
import paypal  # noqa: E402
import store  # noqa: E402


def status():
    print(f"PayPal API: {paypal.base_url()} ({'sandbox' if paypal.is_sandbox() else 'LIVE'})")
    paypal._access_token()
    print("Credentials: OK (got an access token)")
    user = store.get_user()
    print(f"Linked wallet: {'yes, ' + (user['payer_email'] or 'unknown email') if user['vault_id'] else 'no'}")
    print(f"Spending limit: {('$%.2f' % user['spending_cap']) if user['spending_cap'] else 'not set'}")
    print(f"Webhook id configured: {'yes' if os.getenv('PAYPAL_WEBHOOK_ID') else 'no'}")


def register_webhook(url):
    if not url.startswith("https://"):
        sys.exit("Webhook URL must be public https (e.g. from cloudflared or ngrok).")
    webhook_id = paypal.register_webhook(url.rstrip("/") + "/api/paypal/webhook" if not url.endswith("/api/paypal/webhook") else url)
    print(f"Registered. Add this line to server/.env and restart Flask:\nPAYPAL_WEBHOOK_ID={webhook_id}")


def test_charge():
    if not paypal.is_sandbox():
        sys.exit("Refusing: test-charge only runs against the PayPal sandbox.")
    order = checkout.place_order(
        confirmation_token=f"devtest-{secrets.token_hex(8)}",
        product_id="devtest",
        title="SixthCents sandbox test charge",
        size=None,
        amount=1.00,
        currency="USD",
    )
    print(f"Order {order['id']}: status {order['status']}, PayPal order {order['paypal_order_id']}")


if __name__ == "__main__":
    store.init()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    try:
        if cmd == "status":
            status()
        elif cmd == "register-webhook" and len(sys.argv) == 3:
            register_webhook(sys.argv[2])
        elif cmd == "test-charge":
            test_charge()
        else:
            sys.exit(__doc__)
    except (paypal.PayPalError, checkout.CheckoutError) as e:
        sys.exit(f"Error: {e}\n{getattr(e, 'details', '') or ''}")
