import type { AgentResponse, JobStatus } from "./types";

const TRANSIENT_HTTP = new Set([429, 502, 503, 504]);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Short HTTP backoff for proxy/agent flaps. Gemini 30s waits live in Python. */
async function fetchWithBackoff(
  input: RequestInfo | URL,
  init?: RequestInit,
  opts?: { attempts?: number; baseMs?: number }
): Promise<Response> {
  const attempts = opts?.attempts ?? 3;
  const baseMs = opts?.baseMs ?? 1000;
  let lastErr: unknown;

  for (let i = 1; i <= attempts; i++) {
    try {
      const res = await fetch(input, init);
      if (res.ok || !TRANSIENT_HTTP.has(res.status) || i === attempts) {
        return res;
      }
      const delay = baseMs * i + Math.floor(Math.random() * 250);
      await sleep(delay);
      continue;
    } catch (err) {
      lastErr = err;
      if (i === attempts) throw err;
      const delay = baseMs * i + Math.floor(Math.random() * 250);
      await sleep(delay);
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error("fetch failed");
}

/** Browser calls Next.js BFF routes (auth + history claim). */
export async function runAgent(opts: {
  message: string;
  sessionId?: string;
  threadId?: string | null;
  waitForJobs?: boolean;
}): Promise<AgentResponse & { thread_id?: string | null; saved?: boolean }> {
  const res = await fetchWithBackoff("/api/chat/run", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      message: opts.message,
      session_id: opts.sessionId,
      thread_id: opts.threadId,
      wait_for_jobs: opts.waitForJobs ?? false,
    }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Agent error ${res.status}`);
  }
  return (await res.json()) as AgentResponse & {
    thread_id?: string | null;
    saved?: boolean;
  };
}

export async function fetchJob(jobId: string): Promise<JobStatus> {
  const res = await fetchWithBackoff(`/api/chat/jobs/${jobId}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Job poll error ${res.status}`);
  }
  return (await res.json()) as JobStatus;
}

export const TERMINAL = new Set(["completed", "failed", "cancelled"]);
