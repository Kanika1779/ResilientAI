import { useCallback, useState } from "react";
import Header from "./components/Header.jsx";
import ChatWindow from "./components/ChatWindow.jsx";
import ChatInput from "./components/ChatInput.jsx";
import { newSessionId, sendChat } from "./services/api.js";

export default function App() {
  // A fresh session on every page load (lazy initializer runs once per mount).
  const [sessionId, setSessionId] = useState(newSessionId);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState("");

  const handleSend = useCallback(
    async (text) => {
      const message = text.trim();
      if (!message || loading) return false;
      setLoading(true);
      setMessages((m) => [...m, { role: "user", content: message }]);
      try {
        const data = await sendChat({ sessionId, message, systemPrompt });
        setMessages((m) => [...m, { role: "assistant", content: data.reply, metadata: data.metadata }]);
        return true;
      } catch (err) {
        // Shown inline in the conversation. The backend stored nothing for this turn,
        // so the failed user message is marked rather than silently kept.
        setMessages((m) => [
          ...m.slice(0, -1),
          { ...m[m.length - 1], failed: true },
          { role: "error", content: err.message, status: err.status },
        ]);
        return false;
      } finally {
        setLoading(false);
      }
    },
    [sessionId, systemPrompt, loading]
  );

  const handleNewChat = () => {
    setSessionId(newSessionId());
    setMessages([]);
  };

  return (
    <div className="app">
      <Header
        sessionId={sessionId}
        onNewChat={handleNewChat}
        systemPrompt={systemPrompt}
        onSystemPromptChange={setSystemPrompt}
        disabled={loading}
      />
      <ChatWindow messages={messages} loading={loading} />
      <ChatInput onSend={handleSend} disabled={loading} />
    </div>
  );
}
