
import { useState, useRef, useEffect } from "react";
import "./App.css";

const MIN_WIDTH = 190;
const MAX_WIDTH = 380;
const DEFAULT_WIDTH = 250;

function App() {
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_WIDTH);
  const dragging = useRef(false);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    function handlePointerMove(event) {
      if (!dragging.current) return;

      setSidebarWidth(
        Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, event.clientX))
      );
    }

    function handlePointerUp() {
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function startResize(event) {
    event.preventDefault();
    dragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  async function handleSend(event) {
    event.preventDefault();

    const text = message.trim();
    if (!text) return;

    setMessages((previous) => [
      ...previous,
      { role: "user", content: text },
    ]);
    setMessage("");

    // Reserve an assistant message for streamed output.
    const assistantIndex = messages.length + 1;

    setMessages((previous) => [
      ...previous,
      { role: "assistant", content: "" },
    ]);

    try {
      const response = await fetch(
        "https://synapse-ai-9q9j.onrender.com/chat",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ message: text }),
        }
      );

      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }

      if (!response.body) {
        throw new Error("Streaming response is not supported.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });

        if (chunk) {
          setMessages((previous) =>
            previous.map((item, index) =>
              index === assistantIndex
                ? { ...item, content: item.content + chunk }
                : item
            )
          );
        }
      }

      const remaining = decoder.decode();

      if (remaining) {
        setMessages((previous) =>
          previous.map((item, index) =>
            index === assistantIndex
              ? { ...item, content: item.content + remaining }
              : item
          )
        );
      }
    } catch (error) {
      console.error("Chat error:", error);

      setMessages((previous) =>
        previous.map((item, index) =>
          index === assistantIndex
            ? {
                ...item,
                content:
                  "Sorry, I couldn't connect to Synapse AI. Please try again.",
              }
            : item
        )
      );
    }
  }

  return (
    <div className="app">
      <aside
        className={`sidebar ${sidebarOpen ? "open" : "closed"}`}
        style={{ width: sidebarOpen ? sidebarWidth : 0 }}
      >
        {sidebarOpen && (
          <>
            <div className="sidebar-heading">
              <h2>✦ Synapse AI</h2>
              <button
                className="icon-button"
                onClick={() => setSidebarOpen(false)}
                title="Collapse sidebar"
                aria-label="Collapse sidebar"
              >
                ‹
              </button>
            </div>

            <button
              className="new-chat-button"
              onClick={() => setMessages([])}
            >
              <span>＋</span> New chat
            </button>

            <p className="sidebar-section-label">WORKSPACE</p>
            <p className="sidebar-note">
              Your conversations will appear here.
            </p>

            <div className="sidebar-bottom">
              <div className="profile-avatar">S</div>
              <div className="profile-text">
                <strong>Synapse User</strong>
                <span>Personal workspace</span>
              </div>
            </div>

            <div
              className="sidebar-resizer"
              onPointerDown={startResize}
              title="Drag to resize sidebar"
            />
          </>
        )}
      </aside>

      <main className="chat">
        <header className="header">
          <div className="header-left">
            {!sidebarOpen && (
              <button
                className="icon-button reopen-button"
                onClick={() => setSidebarOpen(true)}
                title="Expand sidebar"
                aria-label="Expand sidebar"
              >
                ☰
              </button>
            )}
            <span className="header-title">Synapse AI</span>
          </div>

          <span className="status">
            <span /> Ready
          </span>
        </header>

        <section className="messages">
          <div className="messages-inner">
            {messages.length === 0 ? (
              <div className="welcome">
                <div className="welcome-symbol">✦</div>
                <h1>Where should we begin?</h1>
                <p>Ask a question and start exploring.</p>
              </div>
            ) : (
              messages.map((item, index) => (
                <div
                  className={`message ${item.role}`}
                  key={index}
                >
                  {item.content}
                </div>
              ))
            )}

            <div ref={messagesEndRef} />
          </div>
        </section>

        <div className="composer-area">
          <form className="composer" onSubmit={handleSend}>
            <input
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="Message Synapse AI..."
              aria-label="Message Synapse AI"
            />
            <button type="submit" disabled={!message.trim()}>
              Send ↑
            </button>
          </form>

          <p className="disclaimer">
            Synapse AI can make mistakes. Verify important information.
          </p>
        </div>
      </main>
    </div>
  );
}

export default App;
