/**
 * voice.js — ElevenLabs agent, loaded only when the backend hands us an agent id.
 * The client bundle is fetched from a CDN on the first start, never at boot.
 * Owner: reader agent (book).
 */

import * as TTM from "./ttm.js";

const CLIENT_SRC = "https://cdn.jsdelivr.net/npm/@elevenlabs/client/+esm";

let agentPromise;
let clientPromise;

async function readConfig() {
  try {
    const cfg = await TTM.voiceConfig();
    const id = cfg && cfg.elevenlabsAgentId;
    return typeof id === "string" && id !== "" ? id : null;
  } catch {
    return null;
  }
}

/** Resolves to the agent id, or null when voice is not configured. */
export function agentId() {
  if (!agentPromise) agentPromise = readConfig();
  return agentPromise;
}

function loadClient() {
  if (!clientPromise) {
    clientPromise = import(/* @vite-ignore */ CLIENT_SRC).catch((err) => {
      clientPromise = undefined;
      throw err;
    });
  }
  return clientPromise;
}

async function mic() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return false;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    for (const track of stream.getTracks()) track.stop();
    return true;
  } catch {
    return false;
  }
}

/**
 * Opens a session. `onPage(n)` is the show_page client tool the agent calls to
 * move the reader. Resolves to a handle with end(), or null when it cannot start.
 */
export async function start({ id, dynamicVariables, onPage, onStatus }) {
  if (!id) return null;
  if (!(await mic())) return null;

  const { Conversation } = await loadClient();
  const session = await Conversation.startSession({
    agentId: id,
    connectionType: "webrtc",
    dynamicVariables: dynamicVariables || {},
    clientTools: {
      show_page: (params) => {
        const page = Number(params && params.page);
        if (Number.isFinite(page) && page > 0 && typeof onPage === "function") onPage(page);
      },
    },
    onStatusChange: (info) => {
      if (typeof onStatus === "function") onStatus((info && info.status) || "");
    },
    onError: () => {
      if (typeof onStatus === "function") onStatus("disconnected");
    },
  });

  return {
    end() {
      try {
        session.endSession();
      } catch {
        /* already gone */
      }
    },
  };
}
