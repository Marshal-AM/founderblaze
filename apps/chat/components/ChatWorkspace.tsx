"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { ArrowUp } from "lucide-react";
import { PipelineStage } from "./PipelineStage";
import { ResultsCarousel } from "./ResultsCarousel";
import {
  SERVICE_FORMS,
  ServicePromptModal,
  type ServiceFormDef,
} from "./ServicePromptModal";
import { fetchJob, runAgent, TERMINAL } from "../lib/api";
import { personaForService } from "../lib/services";
import type { ChatMessage, JobStatus } from "../lib/types";

const SESSION_KEY = "founderblaze_chat_session";
const GUEST_WARN_KEY = "founderblaze_guest_warned";

function precedingUserPrompt(
  messages: ChatMessage[],
  agentMsgId: string
): string | undefined {
  const idx = messages.findIndex((m) => m.id === agentMsgId);
  if (idx <= 0) return undefined;
  for (let i = idx - 1; i >= 0; i--) {
    if (messages[i].role === "user") return messages[i].content;
  }
  return undefined;
}

type Props = {
  threadId: string | null;
  onThreadChange: (id: string | null) => void;
  onHistoryChanged: () => void;
  onRequestSignIn: () => void;
};

export function ChatWorkspace({
  threadId,
  onThreadChange,
  onHistoryChanged,
  onRequestSignIn,
}: Props) {
  const { data: session } = useSession();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [activeJobs, setActiveJobs] = useState<Record<string, JobStatus>>({});
  const [guestWarning, setGuestWarning] = useState(false);
  const [serviceForm, setServiceForm] = useState<ServiceFormDef | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const loadingThread = useRef<string | null>(null);

  useEffect(() => {
    const existing = sessionStorage.getItem(SESSION_KEY);
    if (existing) setSessionId(existing);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy, activeJobs, guestWarning]);

  const loadThread = useCallback(
    async (id: string) => {
      if (!session?.user) return;
      loadingThread.current = id;
      try {
        const res = await fetch(`/api/history/${id}`);
        if (!res.ok) return;
        const data = await res.json();
        if (loadingThread.current !== id) return;
        const msgs: ChatMessage[] = (data.messages || []).map(
          (m: {
            id: string;
            role: string;
            content: string;
            meta?: { jobs?: ChatMessage["jobs"]; artifacts?: ChatMessage["artifacts"] };
          }) => ({
            id: m.id,
            role: m.role === "user" ? "user" : "agent",
            content: m.content,
            jobs: m.meta?.jobs,
            artifacts: m.meta?.artifacts,
          })
        );
        setMessages(msgs);
        setActiveJobs({});
        for (const g of data.generations || []) {
          if (!g.job_id) continue;
          setActiveJobs((prev) => ({
            ...prev,
            [g.job_id]: {
              id: g.job_id,
              service: g.service,
              status: g.status,
              step: g.step,
              artifacts: g.artifacts || [],
            },
          }));
        }
        if (data.thread?.agent_session_id) {
          setSessionId(data.thread.agent_session_id);
          sessionStorage.setItem(SESSION_KEY, data.thread.agent_session_id);
        }
      } catch {
        /* ignore */
      }
    },
    [session?.user]
  );

  useEffect(() => {
    if (threadId && session?.user) {
      void loadThread(threadId);
    }
  }, [threadId, session?.user, loadThread]);

  const pendingJobIds = useMemo(() => {
    const ids: string[] = [];
    for (const m of messages) {
      for (const j of m.jobs || []) {
        if (!j.job_id) continue;
        const live = activeJobs[j.job_id];
        if (!live || !TERMINAL.has(live.status)) ids.push(j.job_id);
      }
    }
    // also poll generations restored from history
    for (const [id, job] of Object.entries(activeJobs)) {
      if (!TERMINAL.has(job.status)) ids.push(id);
    }
    return Array.from(new Set(ids)).sort().join(",");
  }, [messages, activeJobs]);

  useEffect(() => {
    const ids = pendingJobIds ? pendingJobIds.split(",") : [];
    if (ids.length === 0) return;
    let cancelled = false;
    const tick = async () => {
      for (const id of ids) {
        if (cancelled) return;
        try {
          const job = await fetchJob(id);
          if (cancelled) return;
          setActiveJobs((prev) => {
            const prevJob = prev[id];
            if (
              prevJob &&
              prevJob.status === job.status &&
              prevJob.step === job.step &&
              (prevJob.artifacts?.length || 0) === (job.artifacts?.length || 0)
            ) {
              return prev;
            }
            return { ...prev, [id]: job };
          });
          if (TERMINAL.has(job.status)) {
            setMessages((msgs) =>
              msgs.map((m) => {
                const owns = (m.jobs || []).some((j) => j.job_id === id);
                if (!owns) return m;
                const existing = m.artifacts || [];
                const incoming = job.artifacts || [];
                const merged = [
                  ...existing,
                  ...incoming.filter(
                    (a) => !existing.some((x) => x.url && a.url && x.url === a.url)
                  ),
                ];
                return { ...m, artifacts: merged, liveJob: job };
              })
            );
            onHistoryChanged();
          }
        } catch (err) {
          const msg =
            err instanceof Error ? err.message : "Failed to refresh job status";
          setError((prev) => prev || msg);
        }
      }
    };
    void tick();
    const handle = setInterval(tick, 4000);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, [pendingJobIds, onHistoryChanged]);

  const showEmpty = messages.length === 0 && !busy;
  const visibleMessages = messages;

  function insertPrompt(prompt: string) {
    setInput(prompt);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 10 * 24)}px`;
    });
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;

    if (!session?.user) {
      const already = sessionStorage.getItem(GUEST_WARN_KEY);
      if (!already) {
        sessionStorage.setItem(GUEST_WARN_KEY, "1");
        setGuestWarning(true);
      }
    } else {
      setGuestWarning(false);
    }

    setError(null);
    setInput("");
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: trimmed,
    };
    setMessages((m) => [...m, userMsg]);
    setBusy(true);
    try {
      const data = await runAgent({
        message: trimmed,
        sessionId,
        threadId,
        waitForJobs: false,
      });
      if (data.session_id) {
        sessionStorage.setItem(SESSION_KEY, data.session_id);
        setSessionId(data.session_id);
      }
      if (data.thread_id) {
        onThreadChange(data.thread_id);
        onHistoryChanged();
      }

      const jobs = data.jobs || [];
      for (const j of jobs) {
        if (j.job_id) {
          setActiveJobs((prev) => ({
            ...prev,
            [j.job_id!]: {
              id: j.job_id!,
              service: j.service || "unknown",
              status: j.status || "queued",
              step: j.step || "starting",
              artifacts: [],
              error: j.error,
            },
          }));
        }
      }

      setMessages((m) => [
        ...m,
        {
          id: `a-${Date.now()}`,
          role: "agent",
          content: data.reply || "(empty reply)",
          meta: data,
          jobs,
          artifacts: data.artifacts || [],
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(input);
  }

  function resetLocal() {
    setMessages([]);
    setActiveJobs({});
    setError(null);
    setGuestWarning(false);
    setSessionId(undefined);
    sessionStorage.removeItem(SESSION_KEY);
  }

  // Expose reset when parent creates new chat without thread
  useEffect(() => {
    if (threadId === null && session?.user) {
      // new chat selected
    }
  }, [threadId, session?.user]);

  // When parent clears thread for "new chat"
  const prevThread = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (prevThread.current !== undefined && threadId === null && prevThread.current !== null) {
      resetLocal();
    }
    if (prevThread.current === undefined && threadId === null) {
      // initial
    }
    prevThread.current = threadId;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  return (
    <section className="panel-card chat-panel">
      <header className="chat-panel-head">
        <div>
          <p className="panel-kicker">Agent</p>
          <p className="panel-title">Conversation</p>
        </div>
        <span className="nav-pill">{session?.user ? "saving" : "guest"}</span>
      </header>

      <div className={showEmpty ? "chat-scroll empty-mode" : "chat-scroll"}>
        {guestWarning && !session?.user ? (
          <div className="guest-banner">
            <div>
              <strong>Not signed in.</strong> This chat and any generated assets
              won&apos;t be saved if you leave.
            </div>
            <button type="button" className="btn-ember-pill" onClick={onRequestSignIn}>
              Sign in
            </button>
          </div>
        ) : null}

        {showEmpty ? (
          <div className="empty-start">
            <ResultsCarousel />
            <div className="empty-copy">
              <h1 className="empty-cta">
                <span className="blaze-word">Blaze</span>
                <span className="empty-cta-rest">up your startup journey</span>
              </h1>
              <p className="empty-guide">
                Type a prompt below, or pick a service to fill in the details.
              </p>
              <div className="feature-badges">
                {SERVICE_FORMS.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className="feature-badge"
                    onClick={() => setServiceForm(s)}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
              <form className="composer empty-composer" onSubmit={onSubmit}>
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => {
                    setInput(e.target.value);
                    const el = e.target;
                    el.style.height = "auto";
                    const max = 10 * 24; // ~10 lines
                    el.style.height = `${Math.min(el.scrollHeight, max)}px`;
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send(input);
                    }
                  }}
                  placeholder="Ask FounderBlaze…"
                  disabled={busy}
                  aria-label="Message"
                  rows={1}
                  className="composer-textarea"
                />
                <button
                  type="submit"
                  className="composer-send"
                  disabled={busy || !input.trim()}
                  aria-label="Send"
                >
                  <ArrowUp
                    className="h-4 w-4"
                    style={{ display: "inline", verticalAlign: "middle" }}
                  />
                </button>
              </form>
            </div>
          </div>
        ) : (
          <>
            {visibleMessages.map((m) => (
              <div key={m.id} className="msg-row">
                <article
                  className={
                    m.role === "user" ? "bubble bubble-user" : "bubble bubble-agent"
                  }
                >
                  {m.content}
                </article>

                {(m.jobs || [])
                  .filter((j) => j.job_id)
                  .map((j) => {
                    const live = activeJobs[j.job_id!] || {
                      id: j.job_id!,
                      service: j.service || "unknown",
                      status: j.status || "queued",
                      step: j.step || "starting",
                      artifacts: m.artifacts,
                      error: j.error,
                    };
                    const persona = personaForService(live.service || j.service);
                    return (
                      <PipelineStage
                        key={j.job_id}
                        persona={persona}
                        prompt={precedingUserPrompt(messages, m.id)}
                        job={live}
                        artifacts={
                          live.status === "completed"
                            ? live.artifacts?.length
                              ? live.artifacts
                              : m.artifacts
                            : undefined
                        }
                      />
                    );
                  })}
              </div>
            ))}

            {busy ? <div className="thinking">Working…</div> : null}
            {error ? <div className="error-banner">{error}</div> : null}
            <div ref={bottomRef} />
          </>
        )}
      </div>

      {!showEmpty ? (
        <form className="composer in-panel" onSubmit={onSubmit}>
          <textarea
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              const el = e.target;
              el.style.height = "auto";
              el.style.height = `${Math.min(el.scrollHeight, 10 * 24)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(input);
              }
            }}
            placeholder="Ask FounderBlaze…"
            disabled={busy}
            aria-label="Message"
            rows={1}
            className="composer-textarea"
          />
          <button
            type="submit"
            className="composer-send"
            disabled={busy || !input.trim()}
            aria-label="Send"
          >
            <ArrowUp
              className="h-4 w-4"
              style={{ display: "inline", verticalAlign: "middle" }}
            />{" "}
            Send
          </button>
        </form>
      ) : null}

      <ServicePromptModal
        service={serviceForm}
        onClose={() => setServiceForm(null)}
        onConfirm={insertPrompt}
      />
    </section>
  );
}
