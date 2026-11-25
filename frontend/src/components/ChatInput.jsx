import { useState } from "react";

const MAX = 4000;

export default function ChatInput({ onSend, disabled }) {
  const [text, setText] = useState("");
  const empty = text.trim().length === 0;
  const tooLong = text.trim().length > MAX;

  const submit = async (e) => {
    e?.preventDefault();
    if (empty || tooLong || disabled) return;
    const draft = text;
    setText(""); // contract: the input is empty after sending, even if the turn fails
    await onSend(draft);
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
  };

  return (
    <form className="input-bar" onSubmit={submit}>
      <textarea
        data-testid="chat-input"
        rows={1}
        placeholder="Message ResilientAI…  (Enter to send, Shift+Enter for a new line)"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        aria-label="Message"
      />
      <div className="input-side">
        {text.length > MAX * 0.9 && (
          <span className={`counter ${tooLong ? "over" : ""}`}>
            {text.trim().length}/{MAX}
          </span>
        )}
        <button type="submit" data-testid="send-button" disabled={empty || tooLong || disabled}>
          Send
        </button>
      </div>
    </form>
  );
}
