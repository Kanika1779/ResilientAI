export default function Header({ sessionId, onNewChat, systemPrompt, onSystemPromptChange, disabled }) {
  return (
    <header className="header">
      <div className="header-row">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">R</span>
          <div>
            <h1>ResilientAI</h1>
            <p className="session" title={sessionId}>
              session <code>{sessionId.slice(0, 14)}…</code>
            </p>
          </div>
        </div>
        <button type="button" className="ghost" onClick={onNewChat} disabled={disabled}>
          New chat
        </button>
      </div>
      <div className="settings">
        <label htmlFor="system-prompt">System prompt (optional)</label>
        <input
          id="system-prompt"
          data-testid="system-prompt-input"
          type="text"
          maxLength={4000}
          placeholder="You are a helpful, concise AI assistant."
          value={systemPrompt}
          onChange={(e) => onSystemPromptChange(e.target.value)}
        />
      </div>
    </header>
  );
}
