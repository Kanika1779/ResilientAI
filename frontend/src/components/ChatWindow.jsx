import { useEffect, useRef } from "react";
import ChatMessage from "./ChatMessage.jsx";
import LoadingIndicator from "./LoadingIndicator.jsx";

export default function ChatWindow({ messages, loading }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, loading]);

  return (
    <main className="chat-window" aria-live="polite">
      {messages.length === 0 && !loading && (
        <div className="empty">
          <h2>Ask anything.</h2>
          <p>
            Each reply shows where it came from: a live model call or the response cache, along with
            latency and token usage.
          </p>
        </div>
      )}
      {messages.map((m, i) => (
        <ChatMessage key={i} message={m} />
      ))}
      {loading && <LoadingIndicator />}
      <div ref={endRef} />
    </main>
  );
}
