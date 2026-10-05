# SixthCents

A voice-first shopping agent for blind and low-vision shoppers, built for the PayPal AI Hackathon.

Say what you want ("black winter coat, size M, under $80"). SixthCents searches real products, describes three options the way you'd want them read aloud (material, fit, how it feels), reads back your pick, and pays with your linked PayPal wallet **only after you say "yes"**.

> **Demo note:** Products are real listings from [Channel3](https://trychannel3.com), but payment goes to **our PayPal sandbox merchant account**, not to the store. No real money moves and nothing ships.

## Quick start (about 2 minutes)

Needs Python 3.10+, Node 18+, and Chrome, Edge, or Safari (for voice).

```bash
# 1. Backend
cd server
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in the keys (see below)
python app.py               # http://localhost:5001

# 2. Frontend (new terminal)
cd client
npm install
npm run dev                 # open http://localhost:5173
```

### Keys in `server/.env`

| Variable | Where to get it |
|---|---|
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | developer.paypal.com → Apps & Credentials → **Sandbox** app. In the app's features, enable **Vault**. |
| `PAYPAL_BASE_URL` | `https://api-m.sandbox.paypal.com` |
| `PAYPAL_WEBHOOK_ID` | Optional, for the spoken "PayPal confirmed" message. See [Webhook](#webhook-optional). |
| `CHANNEL3_API_KEY` | trychannel3.com/sign-up/developer (1,000 free searches a month) |
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `APP_BASE_URL` | `http://localhost:5173` (where PayPal sends you back after linking) |

### Try it

1. **Setup:** press **Link PayPal** and log in with a sandbox **Personal** account (developer.paypal.com → Testing Tools → Sandbox Accounts). Then set a spending limit, for example 100.
2. Press the big mic button (or Space) and say: *"I need a black winter coat, women's size M, under 80 dollars."* You can also type in the text box.
3. Listen to the three options, then say *"option two."*
4. SixthCents reads back the item, size, and total. Say **"yes"**, or press **Yes, buy it**.
5. You'll hear that payment was sent, then that PayPal confirmed it (when the webhook is set up).

## How it works

```
Browser (React)                          Flask server                          External
───────────────                          ────────────                          ────────
Web Speech API ──text──▶ /api/chat ──▶ Claude agent (tool calling) ──▶ Channel3 search
speechSynthesis ◀─reply─              └ propose_purchase → pending + token
"yes" + token ──────────▶ /api/confirm ─▶ strict yes check → checkout ──▶ PayPal Orders v2
                                                                        (vaulted wallet)
poll /api/orders/<id> ◀── PAYMENT.CAPTURE.COMPLETED ◀── /api/paypal/webhook (verified)
```

- **Agent** (`server/agent.py`): Claude (`claude-opus-5-5`) with two tools, `search_products` and `propose_purchase`. **The model has no tool that moves money.** `propose_purchase` only creates a pending purchase with a short-lived, single-use confirmation token, using the price from our own search cache. The token goes to the browser and never to the model.
- **Confirmation gate** (`server/confirm.py`): while a purchase is pending, the user's reply goes to `/api/confirm` with the token. The server, not the AI, checks for an explicit yes ("yes", "yes please", "buy it", …). Anything else, like "yes but in a large", goes back to the agent and cancels the pending purchase.
- **Checkout** (`server/checkout.py`): the only code path that charges. It checks the spending limit on the server again, then charges the vaulted PayPal wallet (Orders v2 with `payment_source.paypal.vault_id`, where PayPal captures it in the same call). `PayPal-Request-Id` makes retries idempotent.
- **PayPal Vault** (`server/paypal.py`): one-time linking through setup token → buyer approval → payment token (`vault_id`). Later charges don't need the buyer to be on PayPal's site.
- **Webhook**: `/api/paypal/webhook` verifies every event with PayPal's `verify-webhook-signature` API before acting on it.

## Accessibility

- A large mic button that has focus when the page loads. Space or Enter starts it, and Escape stops listening and speaking.
- Short tones when the mic opens and closes.
- Agent replies go to an `aria-live` region. Status ("Thinking…") is a `role="status"` region.
- A **"Read replies aloud"** toggle at the top. Screen reader users (VoiceOver, NVDA) can turn off the app voice so replies aren't read twice.
- A labelled text box is always available in case speech recognition fails or is unsupported (for example, Firefox).
- Logical headings and focus order, a thick high-contrast focus ring, dark mode, and reduced-motion support.
- Prompts are written for listening: no markdown, URLs, or spec dumps.

## Webhook (optional)

PayPal can only send webhooks to a public HTTPS URL. For local demos:

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:5001          # prints https://xxxx.trycloudflare.com
cd server && python paypal_check.py register-webhook https://xxxx.trycloudflare.com
# paste the printed PAYPAL_WEBHOOK_ID=... into server/.env and restart Flask
```

Without the webhook, purchases still work. SixthCents tells you PayPal accepted the payment but that the final confirmation hasn't arrived.

## Useful commands

```bash
cd server && source venv/bin/activate
python cli.py                       # talk to the agent in the terminal (text only)
python paypal_check.py              # check PayPal credentials and linked wallet
python paypal_check.py test-charge  # $1.00 sandbox charge to the linked wallet
```

## Limitations (hackathon MVP)

- Single demo user. Conversations are kept in memory and reset when the server restarts.
- The spending limit applies per purchase.
- Sandbox only. Live PayPal vaulting of PayPal wallets requires PayPal to approve reference transactions.
- Channel3 search results often omit size availability. When sizes are unknown, the size you asked for is passed through without being checked.

## License

MIT. See [LICENSE](LICENSE).
