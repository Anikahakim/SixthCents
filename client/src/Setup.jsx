import { useEffect, useState } from "react";

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Server error ${res.status}`);
  return data;
}

/** One-time setup: link a PayPal wallet (Vault) and set a per-purchase spending limit. */
export default function Setup({ account, onAccount, announce }) {
  const [cap, setCap] = useState("");
  const [working, setWorking] = useState(false);

  useEffect(() => {
    if (account?.spending_cap != null) setCap(String(account.spending_cap));
  }, [account?.spending_cap]);

  const run = async (fn) => {
    setWorking(true);
    try {
      await fn();
    } catch (err) {
      announce(err.message);
    } finally {
      setWorking(false);
    }
  };

  const linkPayPal = () =>
    run(async () => {
      const { approve_url } = await api("/api/paypal/setup", { method: "POST" });
      announce("Opening PayPal. You'll come back here when you're done.");
      window.location.assign(approve_url);
    });

  const unlink = () =>
    run(async () => {
      onAccount(await api("/api/paypal/unlink", { method: "POST" }));
      announce("PayPal unlinked.");
    });

  const saveCap = (e) => {
    e.preventDefault();
    run(async () => {
      const updated = await api("/api/account/cap", {
        method: "PUT",
        body: JSON.stringify({ spending_cap: cap }),
      });
      onAccount(updated);
      announce(`Spending limit saved: ${updated.spending_cap.toFixed(2)} dollars per purchase.`);
    });
  };

  if (!account) return null;

  return (
    <section aria-labelledby="setup-heading" className="setup">
      <h2 id="setup-heading">Setup</h2>
      {account.sandbox && <p className="help">Test mode: payments use the PayPal sandbox. No real money moves.</p>}

      <p>
        <strong>PayPal: </strong>
        {account.linked ? `linked${account.payer_email ? ` as ${account.payer_email}` : ""}.` : "not linked yet."}
      </p>
      {account.linked ? (
        <button type="button" className="secondary" onClick={unlink} aria-disabled={working}>
          Unlink PayPal
        </button>
      ) : (
        <button type="button" className="primary" onClick={linkPayPal} aria-disabled={working} aria-describedby="link-help">
          Link PayPal
        </button>
      )}
      {!account.linked && (
        <p id="link-help" className="help">
          Opens PayPal to approve SixthCents once. After that, purchases only happen when you say yes.
        </p>
      )}

      <form onSubmit={saveCap} className="cap-form">
        <label htmlFor="cap-input">Spending limit per purchase, in dollars</label>
        <div className="row">
          <input
            id="cap-input"
            type="number"
            inputMode="decimal"
            min="1"
            max="10000"
            step="0.01"
            value={cap}
            onChange={(e) => setCap(e.target.value)}
            required
          />
          <button type="submit" disabled={working || !cap}>
            Save limit
          </button>
        </div>
      </form>
    </section>
  );
}
