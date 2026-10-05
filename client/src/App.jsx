import { useCallback, useEffect, useRef, useState } from "react";
import {
  earcon,
  recognitionSupported,
  synthesisSupported,
  useSpeechRecognition,
  useSpeechSynthesis,
} from "./speech.js";
import Setup from "./Setup.jsx";

const VOICE_PREF_KEY = "sixthcents.speakReplies";

function loadVoicePref() {
  try {
    const v = localStorage.getItem(VOICE_PREF_KEY);
    return v === null ? true : v === "true";
  } catch {
    return true;
  }
}

function formatPrice(n) {
  return `$${Number(n).toFixed(2)}`;
}

export default function App() {
  const [sessionId, setSessionId] = useState(null);
  const [turns, setTurns] = useState([]);
  const [products, setProducts] = useState([]);
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const [text, setText] = useState("");
  const [speakReplies, setSpeakReplies] = useState(loadVoicePref);
  const [account, setAccount] = useState(null);
  const [order, setOrder] = useState(null);

  const textInputRef = useRef(null);
  const micRef = useRef(null);
  const accountLoaded = useRef(false);
  const tts = useSpeechSynthesis();

  // Put a message in the aria-live region. Clearing first makes repeated text re-announce.
  const announce = useCallback((msg) => {
    setAnnouncement("");
    setTimeout(() => setAnnouncement(msg), 50);
  }, []);

  const send = useCallback(
    async (message) => {
      const trimmed = message.trim();
      if (!trimmed || busy) return;
      tts.cancel();
      setBusy(true);
      setStatus("Thinking…");
      setTurns((t) => [...t, { role: "user", text: trimmed }]);
      try {
        // While a purchase is pending, replies go to the confirmation gate with its token.
        // The server decides whether this is an explicit yes; the AI never can.
        const res = pending
          ? await fetch("/api/confirm", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ session_id: sessionId, confirmation_token: pending.token, message: trimmed }),
            })
          : await fetch("/api/chat", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ session_id: sessionId, message: trimmed }),
            });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `Server error ${res.status}`);
        setSessionId(data.session_id);
        setTurns((t) => [...t, { role: "agent", text: data.reply }]);
        setProducts(data.products || []);
        setPending(data.pending_confirmation);
        if (data.order) setOrder(data.order);
        setStatus("");
        announce(data.reply);
        if (speakReplies) tts.speak(data.reply);
      } catch (err) {
        const msg = `Sorry, something went wrong: ${err.message}`;
        setStatus("");
        setTurns((t) => [...t, { role: "agent", text: msg, error: true }]);
        announce(msg);
        if (speakReplies) tts.speak(msg);
      } finally {
        setBusy(false);
      }
    },
    [busy, sessionId, pending, speakReplies, tts, announce]
  );

  const sayAsAgent = useCallback(
    (msg) => {
      setTurns((t) => [...t, { role: "agent", text: msg }]);
      announce(msg);
      if (speakReplies) tts.speak(msg);
    },
    [announce, speakReplies, tts]
  );

  // After a charge, poll the order until PayPal's webhook confirms (or give up after ~90s).
  useEffect(() => {
    if (!order || order.final) return;
    let tries = 0;
    const timer = setInterval(async () => {
      tries += 1;
      const res = await fetch(`/api/orders/${order.id}`).catch(() => null);
      const data = res?.ok ? await res.json() : null;
      const done = (msg) => {
        clearInterval(timer);
        setOrder((o) => ({ ...o, ...(data || {}), final: true }));
        sayAsAgent(msg);
      };
      if (data?.status === "CAPTURE_CONFIRMED") {
        done(`PayPal confirmed your payment of ${formatPrice(data.amount)}. Your order is complete.`);
      } else if (data?.status === "DENIED") {
        done("PayPal denied that payment, so the order did not go through.");
      } else if (tries >= 45) {
        done(
          data?.status === "COMPLETED"
            ? "PayPal accepted the payment, but its final confirmation hasn't arrived yet. You can check your PayPal account."
            : "I couldn't confirm the payment status. Please check your PayPal account."
        );
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [order, sayAsAgent]);

  const speech = useSpeechRecognition({
    onFinal: (heard) => {
      earcon("stop");
      send(heard);
    },
    onError: (msg) => {
      earcon("stop");
      announce(msg);
      if (speakReplies) tts.speak(msg);
      textInputRef.current?.focus();
    },
  });

  const toggleMic = () => {
    if (busy && !speech.listening) return;
    tts.unlock();
    if (speech.listening) {
      speech.stop();
      return;
    }
    tts.cancel(); // barge-in: stop talking when the user wants to speak
    earcon("start");
    speech.start();
  };

  const onSubmitText = (e) => {
    e.preventDefault();
    tts.unlock();
    send(text);
    setText("");
  };

  const onToggleVoice = (e) => {
    const on = e.target.checked;
    setSpeakReplies(on);
    if (!on) tts.cancel();
    try {
      localStorage.setItem(VOICE_PREF_KEY, String(on));
    } catch {
      /* preference just won't persist */
    }
  };

  // Escape stops listening and speaking from anywhere on the page.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        tts.cancel();
        speech.stop();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tts, speech]);

  useEffect(() => {
    if (recognitionSupported) micRef.current?.focus();
    else textInputRef.current?.focus();
  }, []);

  // Load account status, finishing PayPal linking if we just came back from PayPal.
  useEffect(() => {
    if (accountLoaded.current) return; // StrictMode runs effects twice; complete linking only once
    accountLoaded.current = true;
    const params = new URLSearchParams(window.location.search);
    const result = params.get("paypal");
    if (result) window.history.replaceState(null, "", window.location.pathname);

    (async () => {
      try {
        if (result === "return") {
          const res = await fetch("/api/paypal/complete", { method: "POST" });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.error || "PayPal linking didn't finish.");
          setAccount(data);
          announce("PayPal is linked.");
          return;
        }
        if (result === "cancel") announce("PayPal linking was cancelled.");
        const res = await fetch("/api/account");
        if (res.ok) setAccount(await res.json());
      } catch (err) {
        announce(err.message);
        const res = await fetch("/api/account").catch(() => null);
        if (res?.ok) setAccount(await res.json());
      }
    })();
  }, [announce]);

  const setupDone = account?.linked && account?.spending_cap != null;
  const setup = <Setup account={account} onAccount={setAccount} announce={announce} />;

  const micLabel = speech.listening ? "Stop listening" : busy ? "Please wait" : "Press to talk";

  return (
    <div className="app">
      <header>
        <h1>SixthCents</h1>
        <p className="tagline">Say what you want to buy. I'll find three options, describe them, and only pay after you say yes.</p>
        {synthesisSupported && (
          <label className="toggle">
            <input type="checkbox" checked={speakReplies} onChange={onToggleVoice} />
            Read replies aloud with the app voice. Turn this off if your screen reader already reads them.
          </label>
        )}
      </header>

      <main>
        {account && !setupDone && setup}

        <section aria-labelledby="talk-heading" className="talk">
          <h2 id="talk-heading" className="visually-hidden">Talk to SixthCents</h2>

          {recognitionSupported ? (
            <button
              ref={micRef}
              type="button"
              className={`mic ${speech.listening ? "listening" : ""}`}
              onClick={toggleMic}
              aria-disabled={busy && !speech.listening}
              aria-describedby="mic-help"
            >
              <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" className="mic-icon">
                <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z" />
              </svg>
              <span>{micLabel}</span>
            </button>
          ) : (
            <p className="notice" role="note">
              Voice input isn't supported in this browser. Use Chrome, Edge, or Safari for voice, or type below.
            </p>
          )}
          <p id="mic-help" className="help">
            Press Space or Enter to start, then speak. It stops on its own when you pause. Press Escape to stop speech.
          </p>

          {speech.listening && (
            <p className="interim" aria-hidden="true">
              {speech.interim || "Listening…"}
            </p>
          )}

          <form onSubmit={onSubmitText} className="text-form">
            <label htmlFor="text-input">Or type your request</label>
            <div className="row">
              <input
                id="text-input"
                ref={textInputRef}
                type="text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                autoComplete="off"
                placeholder="Black winter coat, size M, under $80"
              />
              <button type="submit" disabled={busy || !text.trim()}>
                Send
              </button>
            </div>
          </form>

          <p role="status" className="status">
            {status}
          </p>
        </section>

        {/* Screen readers announce each new agent reply from here. */}
        <div aria-live="polite" aria-atomic="true" className="visually-hidden">
          {announcement}
        </div>

        {pending && (
          <section aria-labelledby="confirm-heading" className="confirm">
            <h2 id="confirm-heading">Ready to confirm</h2>
            <dl>
              <dt>Item</dt>
              <dd>{pending.title}</dd>
              <dt>Size</dt>
              <dd>{pending.size || "Not applicable"}</dd>
              <dt>Total</dt>
              <dd>{formatPrice(pending.total)}</dd>
            </dl>
            <div className="row confirm-buttons">
              <button type="button" className="primary" onClick={() => send("yes")} aria-disabled={busy}>
                Yes, buy it
              </button>
              <button type="button" className="secondary" onClick={() => send("no")} aria-disabled={busy}>
                No, cancel
              </button>
            </div>
            <p className="help">
              Or say "yes" or "no". Paid with your linked PayPal. Demo: payment goes to the SixthCents sandbox merchant, not the
              store.
            </p>
          </section>
        )}

        {products.length > 0 && (
          <section aria-labelledby="options-heading">
            <h2 id="options-heading">Options</h2>
            <ol className="products">
              {products.map((p, i) => (
                <li key={p.id} className="product">
                  {p.image_url && <img src={p.image_url} alt={p.image_alt || ""} />}
                  <div>
                    <h3>
                      Option {i + 1}: {p.title}
                    </h3>
                    <p className="price">{formatPrice(p.price)}</p>
                    <p>
                      {[p.brand, p.retailer && `from ${p.retailer}`].filter(Boolean).join(" ")}
                      {p.materials?.length > 0 && `. Materials: ${p.materials.join(", ")}`}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        )}

        {turns.length > 0 && (
          <section aria-labelledby="history-heading">
            <h2 id="history-heading">Conversation</h2>
            <ol className="history">
              {turns.map((t, i) => (
                <li key={i} className={`turn ${t.role} ${t.error ? "error" : ""}`}>
                  <span className="who">{t.role === "user" ? "You said:" : "SixthCents said:"}</span> {t.text}
                </li>
              ))}
            </ol>
          </section>
        )}

        {setupDone && setup}
      </main>

    </div>
  );
}
