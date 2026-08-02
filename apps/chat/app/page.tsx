"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

type Artifact = {
  type?: string;
  url?: string | null;
  object_key?: string | null;
  mime_type?: string | null;
};

type AgentResponse = {
  session_id: string;
  reply: string;
  tool_calls?: Array<{ name: string; ok?: boolean; error?: string }>;
  jobs?: Array<{ job_id?: string; service?: string; status?: string }>;
  artifacts?: Artifact[];
};

type ChatMessage = {
  id: string;
  role: "user" | "agent";
  content: string;
  meta?: AgentResponse;
};

const SESSION_KEY = "founderblaze_chat_session";

function agentBase(): string {
  return (process.env.NEXT_PUBLIC_AGENT_URL || "http://localhost:4022").replace(
    /\/$/,
    ""
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "agent",
      content:
        "FounderBlaze agent ready. Ask what services I can run, or request a demo video, brand kit, outreach pack, and more.",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const existing = sessionStorage.getItem(SESSION_KEY);
    if (existing) setSessionId(existing);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const base = useMemo(() => agentBase(), []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setError(null);
    setInput("");
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: text,
    };
    setMessages((m) => [...m, userMsg]);
    setBusy(true);
    try {
      const res = await fetch(`${base}/v1/agent/run`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `Agent error ${res.status}`);
      }
      const data = (await res.json()) as AgentResponse;
      if (data.session_id) {
        sessionStorage.setItem(SESSION_KEY, data.session_id);
        setSessionId(data.session_id);
      }
      setMessages((m) => [
        ...m,
        {
          id: `a-${Date.now()}`,
          role: "agent",
          content: data.reply || "(empty reply)",
          meta: data,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      style={{
        width: "min(720px, 100%)",
        margin: "0 auto",
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        padding: "28px 18px 20px",
      }}
    >
      <header style={{ marginBottom: 22 }}>
        <div
          style={{
            fontSize: 12,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--muted)",
            fontWeight: 600,
          }}
        >
          FounderBlaze
        </div>
        <h1
          style={{
            margin: "6px 0 0",
            fontSize: 34,
            letterSpacing: "-0.03em",
            fontWeight: 700,
          }}
        >
          Agent chat
        </h1>
        <p style={{ margin: "8px 0 0", color: "var(--muted)", fontSize: 14 }}>
          Connected to <code>{base}</code>
        </p>
      </header>

      <section
        style={{
          flex: 1,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 12,
          paddingBottom: 12,
        }}
      >
        {messages.map((m) => (
          <article
            key={m.id}
            style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "92%",
              background: m.role === "user" ? "var(--user)" : "var(--agent)",
              color: m.role === "user" ? "#f8fafc" : "var(--ink)",
              border: m.role === "user" ? "none" : "1px solid var(--line)",
              borderRadius: m.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
              padding: "12px 14px",
              whiteSpace: "pre-wrap",
              lineHeight: 1.45,
              fontSize: 15,
            }}
          >
            {m.content}
            {m.meta?.tool_calls && m.meta.tool_calls.length > 0 ? (
              <details style={{ marginTop: 10, fontSize: 12, opacity: 0.85 }}>
                <summary>Tools / jobs</summary>
                <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                  {m.meta.tool_calls.map((t, i) => (
                    <li key={`${t.name}-${i}`}>
                      {t.name}
                      {t.ok === false ? ` — failed: ${t.error || "?"}` : " — ok"}
                    </li>
                  ))}
                  {(m.meta.jobs || []).map((j, i) => (
                    <li key={`${j.job_id}-${i}`}>
                      job {j.job_id} ({j.service}) → {j.status}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
            {m.meta?.artifacts && m.meta.artifacts.some((a) => a.url) ? (
              <div style={{ marginTop: 10, fontSize: 13 }}>
                {m.meta.artifacts
                  .filter((a) => a.url)
                  .map((a, i) => (
                    <div key={i}>
                      <a href={a.url!} target="_blank" rel="noreferrer">
                        Download {a.type || "artifact"}
                      </a>
                    </div>
                  ))}
              </div>
            ) : null}
          </article>
        ))}
        {busy ? (
          <div style={{ color: "var(--muted)", fontSize: 13 }}>Working…</div>
        ) : null}
        {error ? (
          <div style={{ color: "#b91c1c", fontSize: 13, whiteSpace: "pre-wrap" }}>
            {error}
          </div>
        ) : null}
        <div ref={bottomRef} />
      </section>

      <form
        onSubmit={onSubmit}
        style={{
          display: "flex",
          gap: 10,
          borderTop: "1px solid var(--line)",
          paddingTop: 14,
          marginTop: 8,
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask FounderBlaze…"
          disabled={busy}
          style={{
            flex: 1,
            border: "1px solid var(--line)",
            borderRadius: 12,
            padding: "12px 14px",
            fontSize: 15,
            background: "var(--panel)",
            color: "var(--ink)",
            outline: "none",
          }}
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          style={{
            border: "none",
            borderRadius: 12,
            padding: "0 18px",
            background: "var(--ink)",
            color: "#fff",
            fontWeight: 600,
            cursor: busy ? "wait" : "pointer",
            opacity: busy || !input.trim() ? 0.5 : 1,
          }}
        >
          Send
        </button>
      </form>
    </main>
  );
}
