/**
 * The thumb dock — two icon buttons, chat and voice. Owner: ui-polish agent.
 * Pairs with the `.dock` block in css/counter.css.
 *
 * "In the bottom there should be both a chat and a voice button (just icons) so that the
 * voice is easier accessible." One element, body level, fixed: Pick, Book and the Parts
 * sheet all show the same pair in the same place, because a control that moves between
 * screens is a control you have to look for.
 *
 * Bottom LEFT, deliberately. The voice orb docks bottom right (css/voice-orb.css), so the
 * opposite corner is the only one where the pair can never sit under it.
 *
 * It knows nothing about voice: the mic dispatches `mechanica:voice` and js/voice-session.js
 * owns everything after that. Chat is a callback, so whichever screen is live decides which
 * conversation opens.
 */

const CHAT_PATH = "M3 4h18v12H9l-6 5V4z";
const MIC_BODY = "M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z";
const MIC_ARC = "M5 11a7 7 0 0 0 14 0M12 18v3";

let el = null;
let chatBtn = null;
let micBtn = null;
let onChat = null;

function glyph(paths, stroke) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const d of paths) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    if (stroke) {
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "2.2");
      path.setAttribute("stroke-linecap", "round");
    } else {
      path.setAttribute("fill", "currentColor");
    }
    svg.append(path);
  }
  return svg;
}

function button(className, label, node) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = className;
  btn.setAttribute("aria-label", label);
  btn.append(node);
  return btn;
}

/** Builds the dock once. Safe to call from every screen's module body. */
export function ensureDock() {
  if (el) return el;
  el = document.createElement("div");
  el.className = "dock";
  el.setAttribute("role", "group");
  el.setAttribute("aria-label", "Chat and voice");

  chatBtn = button("dock-btn dock-chat", "Chat", glyph([CHAT_PATH], false));
  chatBtn.hidden = true;
  chatBtn.addEventListener("click", () => {
    if (typeof onChat === "function") onChat();
  });

  micBtn = button("dock-btn dock-mic", "Voice", glyph([MIC_BODY, MIC_ARC], true));
  micBtn.addEventListener("click", () => {
    window.dispatchEvent(new CustomEvent("mechanica:voice", { detail: { action: "start" } }));
  });

  el.append(chatBtn, micBtn);
  document.body.append(el);
  return el;
}

/** The live screen claims the chat button. Pass null to take it away again. */
export function setChat(handler) {
  ensureDock();
  onChat = typeof handler === "function" ? handler : null;
  chatBtn.hidden = !onChat;
}

/** Whether the chat button is offered at all — a manual has to exist first. */
export function showChat(on) {
  ensureDock();
  chatBtn.hidden = !on || !onChat;
}
