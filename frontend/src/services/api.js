// All backend calls live here. The frontend never sees API keys or talks to a provider.

export const API_BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export function newSessionId() {
  // crypto.randomUUID needs a secure context; fall back for plain-http hosts.
  if (globalThis.crypto?.randomUUID) return `s-${crypto.randomUUID()}`;
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function describe422(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const d = detail[0];
    const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : "input";
    return `Invalid ${field}: ${d.msg}`;
  }
  return "The request was invalid.";
}

export async function sendChat({ sessionId, message, systemPrompt }) {
  const body = { session_id: sessionId, message };
  if (systemPrompt && systemPrompt.trim()) body.system_prompt = systemPrompt.trim();

  let res;
  try {
    res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }

  let data = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON body */
  }

  if (res.ok && data) return data;
  if (res.status === 422) throw new ApiError(describe422(data?.detail), 422);
  if (res.status === 503)
    throw new ApiError("AI services are temporarily unavailable. Please try again.", 503);
  throw new ApiError("Something went wrong on the server. Please try again.", res.status);
}
