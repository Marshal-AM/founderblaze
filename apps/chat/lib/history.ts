import type { Artifact } from "./types";
import { getPool } from "./db";
import { ensureChatSchema } from "./migrate";

export type ThreadRow = {
  id: string;
  title: string;
  agent_session_id: string | null;
  created_at: string;
  updated_at: string;
};

export type GenerationRow = {
  id: string;
  job_id: string;
  service: string;
  prompt: string | null;
  status: string;
  step: string | null;
  artifacts: Artifact[];
  thread_id: string | null;
  created_at: string;
  updated_at: string;
};

function titleFromPrompt(prompt: string): string {
  const t = prompt.trim().replace(/\s+/g, " ");
  return t.length > 56 ? `${t.slice(0, 56)}…` : t || "New chat";
}

export async function listThreads(userId: string): Promise<ThreadRow[]> {
  await ensureChatSchema();
  const { rows } = await getPool().query(
    `SELECT id, title, agent_session_id,
            created_at::text, updated_at::text
     FROM chat_threads
     WHERE user_id = $1
     ORDER BY updated_at DESC
     LIMIT 100`,
    [userId]
  );
  return rows;
}

export async function createThread(
  userId: string,
  opts?: { title?: string; agentSessionId?: string }
): Promise<ThreadRow> {
  await ensureChatSchema();
  const { rows } = await getPool().query(
    `INSERT INTO chat_threads (user_id, title, agent_session_id)
     VALUES ($1, $2, $3)
     RETURNING id, title, agent_session_id, created_at::text, updated_at::text`,
    [userId, opts?.title || "New chat", opts?.agentSessionId || null]
  );
  return rows[0];
}

export async function getThread(
  userId: string,
  threadId: string
): Promise<ThreadRow | null> {
  await ensureChatSchema();
  const { rows } = await getPool().query(
    `SELECT id, title, agent_session_id, created_at::text, updated_at::text
     FROM chat_threads WHERE id = $1 AND user_id = $2`,
    [threadId, userId]
  );
  return rows[0] || null;
}

export async function touchThread(
  userId: string,
  threadId: string,
  opts?: { title?: string; agentSessionId?: string }
): Promise<void> {
  await ensureChatSchema();
  await getPool().query(
    `UPDATE chat_threads
     SET updated_at = NOW(),
         title = COALESCE($3, title),
         agent_session_id = COALESCE($4, agent_session_id)
     WHERE id = $1 AND user_id = $2`,
    [threadId, userId, opts?.title ?? null, opts?.agentSessionId ?? null]
  );
}

export async function appendMessages(
  userId: string,
  threadId: string,
  messages: Array<{ role: string; content: string; meta?: unknown }>
): Promise<void> {
  await ensureChatSchema();
  const pool = getPool();
  for (const m of messages) {
    await pool.query(
      `INSERT INTO chat_messages (thread_id, user_id, role, content, meta)
       VALUES ($1, $2, $3, $4, $5::jsonb)`,
      [
        threadId,
        userId,
        m.role,
        m.content,
        JSON.stringify(m.meta ?? {}),
      ]
    );
  }
  await pool.query(
    `UPDATE chat_threads SET updated_at = NOW() WHERE id = $1 AND user_id = $2`,
    [threadId, userId]
  );
}

export async function listMessages(
  userId: string,
  threadId: string
): Promise<
  Array<{ id: string; role: string; content: string; meta: unknown; created_at: string }>
> {
  await ensureChatSchema();
  const thread = await getThread(userId, threadId);
  if (!thread) return [];
  const { rows } = await getPool().query(
    `SELECT id, role, content, meta, created_at::text
     FROM chat_messages
     WHERE thread_id = $1
     ORDER BY created_at ASC`,
    [threadId]
  );
  return rows;
}

export async function claimGenerations(
  userId: string,
  threadId: string | null,
  prompt: string,
  jobs: Array<{ job_id?: string; service?: string; status?: string; step?: string | null }>
): Promise<void> {
  await ensureChatSchema();
  const pool = getPool();
  for (const j of jobs) {
    if (!j.job_id) continue;
    await pool.query(
      `INSERT INTO chat_generations
         (user_id, thread_id, job_id, service, prompt, status, step)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (job_id) DO UPDATE
         SET status = EXCLUDED.status,
             step = COALESCE(EXCLUDED.step, chat_generations.step),
             updated_at = NOW()`,
      [
        userId,
        threadId,
        j.job_id,
        j.service || "unknown",
        prompt,
        j.status || "queued",
        j.step || "starting",
      ]
    );
  }
  if (threadId && prompt) {
    await touchThread(userId, threadId, { title: titleFromPrompt(prompt) });
  }
}

export async function updateGenerationFromJob(
  userId: string,
  jobId: string,
  job: {
    status?: string;
    step?: string | null;
    artifacts?: Artifact[];
  }
): Promise<boolean> {
  await ensureChatSchema();
  const { rowCount } = await getPool().query(
    `UPDATE chat_generations
     SET status = COALESCE($3, status),
         step = COALESCE($4, step),
         artifacts = COALESCE($5::jsonb, artifacts),
         updated_at = NOW()
     WHERE job_id = $1 AND user_id = $2`,
    [
      jobId,
      userId,
      job.status ?? null,
      job.step ?? null,
      job.artifacts ? JSON.stringify(job.artifacts) : null,
    ]
  );
  return (rowCount ?? 0) > 0;
}

export async function userOwnsJob(
  userId: string,
  jobId: string
): Promise<boolean> {
  await ensureChatSchema();
  const { rows } = await getPool().query(
    `SELECT 1 FROM chat_generations WHERE job_id = $1 AND user_id = $2`,
    [jobId, userId]
  );
  return rows.length > 0;
}

export async function listAssets(userId: string): Promise<GenerationRow[]> {
  await ensureChatSchema();
  const { rows } = await getPool().query(
    `SELECT id, job_id, service, prompt, status, step, artifacts,
            thread_id::text, created_at::text, updated_at::text
     FROM chat_generations
     WHERE user_id = $1
     ORDER BY created_at DESC
     LIMIT 200`,
    [userId]
  );
  return rows.map((r) => ({
    ...r,
    artifacts: Array.isArray(r.artifacts) ? r.artifacts : [],
  }));
}

export async function listThreadGenerations(
  userId: string,
  threadId: string
): Promise<GenerationRow[]> {
  await ensureChatSchema();
  const { rows } = await getPool().query(
    `SELECT id, job_id, service, prompt, status, step, artifacts,
            thread_id::text, created_at::text, updated_at::text
     FROM chat_generations
     WHERE user_id = $1 AND thread_id = $2
     ORDER BY created_at ASC`,
    [userId, threadId]
  );
  return rows.map((r) => ({
    ...r,
    artifacts: Array.isArray(r.artifacts) ? r.artifacts : [],
  }));
}
