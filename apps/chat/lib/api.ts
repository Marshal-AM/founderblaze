import type { AgentResponse, JobStatus } from "./types";

/** Browser calls Next.js BFF routes (auth + history claim). */
export async function runAgent(opts: {
  message: string;
  sessionId?: string;
  threadId?: string | null;
  waitForJobs?: boolean;
}): Promise<AgentResponse & { thread_id?: string | null; saved?: boolean }> {
  const res = await fetch("/api/chat/run", {
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
  const res = await fetch(`/api/chat/jobs/${jobId}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Job poll error ${res.status}`);
  }
  return (await res.json()) as JobStatus;
}

export const TERMINAL = new Set(["completed", "failed", "cancelled"]);
