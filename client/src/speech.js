import { useCallback, useEffect, useRef, useState } from "react";

const Recognition = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

export const recognitionSupported = Boolean(Recognition);
export const synthesisSupported = typeof window !== "undefined" && "speechSynthesis" in window;

const RECOGNITION_ERRORS = {
  "not-allowed": "Microphone access is blocked. Allow the microphone in your browser settings, or type your request instead.",
  "service-not-allowed": "Speech recognition isn't available in this browser. Please type your request instead.",
  "no-speech": "I didn't hear anything. Press the microphone button and try again.",
  "audio-capture": "No microphone was found. Please type your request instead.",
  network: "Speech recognition needs an internet connection. Please type your request instead.",
};

/** Push-to-talk speech recognition. Calls onFinal(text) once per utterance. */
export function useSpeechRecognition({ onFinal, onError }) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const recRef = useRef(null);
  const handlers = useRef({ onFinal, onError });
  handlers.current = { onFinal, onError };

  const stop = useCallback(() => recRef.current?.stop(), []);

  const start = useCallback(() => {
    if (!Recognition || recRef.current) return;
    const rec = new Recognition();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    let finalText = "";

    rec.onresult = (e) => {
      let partial = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript;
        else partial += e.results[i][0].transcript;
      }
      setInterim(finalText + partial);
    };
    rec.onerror = (e) => {
      if (e.error === "aborted") return;
      handlers.current.onError?.(RECOGNITION_ERRORS[e.error] || `Speech recognition error: ${e.error}. Please type instead.`, e.error);
    };
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
      setInterim("");
      const text = finalText.trim();
      if (text) handlers.current.onFinal(text);
    };

    recRef.current = rec;
    setListening(true);
    try {
      rec.start();
    } catch {
      recRef.current = null;
      setListening(false);
    }
  }, []);

  useEffect(() => () => recRef.current?.abort(), []);

  return { listening, interim, start, stop };
}

/** Text-to-speech that queues sentences (Chrome cuts off long single utterances). */
export function useSpeechSynthesis() {
  const [speaking, setSpeaking] = useState(false);

  const cancel = useCallback(() => {
    if (!synthesisSupported) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  const speak = useCallback((text) => {
    if (!synthesisSupported || !text) return;
    window.speechSynthesis.cancel();
    const parts = text.match(/[^.!?]+[.!?]*\s*/g) || [text];
    parts.forEach((part, i) => {
      const u = new SpeechSynthesisUtterance(part.trim());
      u.lang = "en-US";
      u.rate = 1;
      if (i === 0) u.onstart = () => setSpeaking(true);
      if (i === parts.length - 1) {
        u.onend = () => setSpeaking(false);
        u.onerror = () => setSpeaking(false);
      }
      window.speechSynthesis.speak(u);
    });
  }, []);

  // Safari only allows speech that starts from a user gesture; call this inside a click/keypress.
  const unlock = useCallback(() => {
    if (!synthesisSupported) return;
    const u = new SpeechSynthesisUtterance("");
    u.volume = 0;
    window.speechSynthesis.speak(u);
  }, []);

  return { speaking, speak, cancel, unlock };
}

/** Short tones so people know when the mic opens and closes without looking. */
let audioCtx;
export function earcon(kind) {
  try {
    audioCtx ||= new (window.AudioContext || window.webkitAudioContext)();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.frequency.value = kind === "start" ? 880 : 520;
    gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.15);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.15);
  } catch {
    /* audio is a nicety; ignore failures */
  }
}
