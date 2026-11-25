export default function LoadingIndicator() {
  return (
    <div className="msg msg-assistant" data-testid="loading-indicator" aria-label="Waiting for reply">
      <div className="bubble typing">
        <span />
        <span />
        <span />
      </div>
    </div>
  );
}
