/**
 * Web Speech dictation. Same shape as deepgram.js so the ask bar can swap one for the other.
 *   supported, prime(terms), start(onText, onEnd), stop()
 */

const ctor =
  typeof window === "undefined"
    ? undefined
    : window.SpeechRecognition || window.webkitSpeechRecognition;

export const supported = ctor !== undefined;

let active = null;

export function prime() {
  /* keyterms are a Deepgram feature */
}

export function stop() {
  const r = active;
  active = null;
  if (!r) return;
  r.onresult = null;
  r.onend = null;
  r.onerror = null;
  try {
    r.abort();
  } catch {
    try {
      r.stop();
    } catch {
      /* already gone */
    }
  }
}

export function start(onText, onEnd) {
  if (!ctor) {
    onEnd();
    return;
  }
  stop();
  const r = new ctor();
  r.lang = "en-US";
  r.interimResults = true;
  r.continuous = false;
  r.maxAlternatives = 1;
  r.onresult = (e) => {
    let text = "";
    let final = false;
    for (let i = 0; i < e.results.length; i++) {
      const result = e.results[i];
      text += result[0].transcript;
      if (result.isFinal) final = true;
    }
    onText(text.trim(), final);
  };
  const end = () => {
    if (active === r) active = null;
    onEnd();
  };
  r.onend = end;
  r.onerror = end;
  active = r;
  try {
    r.start();
  } catch {
    end();
  }
}
