import Metadata from "./Metadata.jsx";

export default function ChatMessage({ message }) {
  if (message.role === "user") {
    return (
      <div className={`msg msg-user${message.failed ? " msg-failed" : ""}`} data-testid="user-message">
        <div className="bubble">{message.content}</div>
        {message.failed && <span className="failed-note">Not sent. This message wasn't saved.</span>}
      </div>
    );
  }
  if (message.role === "error") {
    return (
      <div className="msg msg-error" role="alert" data-testid="error-message">
        <div className="bubble">{message.content}</div>
      </div>
    );
  }
  return (
    <div className="msg msg-assistant" data-testid="assistant-message">
      <div className="bubble">{message.content}</div>
      {message.metadata && <Metadata meta={message.metadata} />}
    </div>
  );
}
