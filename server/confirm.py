"""Confirmation gate: turns an explicit spoken "yes" plus a valid token into a charge.

The decision is made here with a strict allowlist, not by the LLM. Anything that
isn't a clear yes or no goes back to the agent (which also cancels the proposal).
"""
import re
import secrets
import time

import agent
import checkout

_YES = re.compile(
    r"^(yes|yeah|yep|yup|confirm|confirmed|buy it|place (the )?order)"
    r"( (please|buy it|confirm|do it|go ahead|place (the |my )?order|thats right|correct))*$"
)
_NO = re.compile(r"^(no|nope|cancel|stop|dont buy it|do not buy it|never ?mind)( (thanks|thank you|cancel|please|dont buy it))*$")


def _normalize(text):
    text = text.lower().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^a-z ]+", " ", text).split())


def classify(text):
    t = _normalize(text)
    if _YES.match(t):
        return "yes"
    if _NO.match(t):
        return "no"
    return "other"


def handle(session_id, token, message):
    session = agent.find_session(session_id) if session_id else None
    if session is None:
        return {"error": "Unknown session. Please start again."}, 400

    with session["lock"]:
        pending = session["pending"]
        token_ok = (
            pending is not None
            and isinstance(token, str)
            and secrets.compare_digest(token, pending["token"])
            and time.time() < pending["expires_at"]
        )
        intent = classify(message)

        if intent == "other":
            pass  # fall through to the agent below, outside the lock
        elif not token_ok:
            session["pending"] = None
            reply = "That confirmation has expired. Tell me which option you want and I'll read it back again."
            agent.record_exchange(session, message, reply)
            return agent.result(session, reply), 200
        elif intent == "no":
            session["pending"] = None
            reply = "Okay, I cancelled that. Nothing was charged. Want to hear the other options or search for something else?"
            agent.record_exchange(session, message, reply)
            return agent.result(session, reply), 200
        else:
            session["pending"] = None  # single use, cleared before charging
            product = pending["product"]
            try:
                order = checkout.place_order(
                    confirmation_token=pending["token"],
                    product_id=product["id"],
                    title=product["title"],
                    size=pending["size"],
                    amount=pending["total"],
                    currency=pending["currency"],
                )
            except checkout.CheckoutError as e:
                reply = f"I couldn't complete the payment. {e} Nothing was charged."
                agent.record_exchange(session, message, reply)
                return agent.result(session, reply), 200

            size = f", size {pending['size']}" if pending["size"] else ""
            reply = (
                f"Done. I sent ${order['amount']:.2f} through PayPal for {product['title']}{size}. "
                "I'll tell you as soon as PayPal confirms it."
            )
            agent.record_exchange(session, message, reply)
            out = agent.result(session, reply)
            out["order"] = {"id": order["id"], "status": order["status"], "amount": order["amount"]}
            return out, 200

    return agent.chat(session_id, message), 200
