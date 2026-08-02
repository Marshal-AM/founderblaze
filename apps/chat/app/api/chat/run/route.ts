import { NextResponse } from "next/server";
import { auth } from "@/auth";
import {
  appendMessages,
  claimGenerations,
  createThread,
  getThread,
  touchThread,
} from "@/lib/history";
import { ensureChatSchema } from "@/lib/migrate";

function agentBase(): string {
  return (
    process.env.AGENT_URL ||
    process.env.NEXT_PUBLIC_AGENT_URL ||
    "http://localhost:4022"
  ).replace(/\/$/, "");
}

export async function POST(req: Request) {
  try {
    await ensureChatSchema();
    const session = await auth();
    const body = (await req.json()) as {
      message?: string;
      session_id?: string;
      thread_id?: string | null;
      wait_for_jobs?: boolean;
    };
    const message = String(body.message || "").trim();
    if (!message) {
      return NextResponse.json({ error: "message required" }, { status: 400 });
    }

    const res = await fetch(`${agentBase()}/v1/agent/run`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: body.session_id,
        wait_for_jobs: body.wait_for_jobs ?? false,
      }),
    });

    const text = await res.text();
    if (!res.ok) {
      return NextResponse.json(
        { error: text || `Agent error ${res.status}` },
        { status: res.status }
      );
    }

    const data = JSON.parse(text) as {
      session_id: string;
      reply: string;
      tool_calls?: unknown[];
      jobs?: Array<{
        job_id?: string;
        service?: string;
        status?: string;
        step?: string | null;
      }>;
      artifacts?: unknown[];
      pending?: boolean;
    };

    let threadId: string | null = body.thread_id || null;
    const userId = session?.user?.id;

    if (userId) {
      if (threadId) {
        const existing = await getThread(userId, threadId);
        if (!existing) threadId = null;
      }
      if (!threadId) {
        const thread = await createThread(userId, {
          title: message.slice(0, 56),
          agentSessionId: data.session_id,
        });
        threadId = thread.id;
      } else {
        await touchThread(userId, threadId, {
          agentSessionId: data.session_id,
        });
      }

      await appendMessages(userId, threadId, [
        { role: "user", content: message },
        {
          role: "assistant",
          content: data.reply || "",
          meta: {
            tool_calls: data.tool_calls,
            jobs: data.jobs,
            artifacts: data.artifacts,
          },
        },
      ]);

      if (data.jobs?.length) {
        await claimGenerations(userId, threadId, message, data.jobs);
      }
    }

    return NextResponse.json({
      ...data,
      thread_id: threadId,
      saved: Boolean(userId),
    });
  } catch (err) {
    console.error("chat run failed", err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Run failed" },
      { status: 500 }
    );
  }
}
