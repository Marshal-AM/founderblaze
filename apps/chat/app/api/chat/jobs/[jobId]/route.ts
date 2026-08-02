import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { updateGenerationFromJob, userOwnsJob } from "@/lib/history";
import { ensureChatSchema } from "@/lib/migrate";

function agentBase(): string {
  return (
    process.env.AGENT_URL ||
    process.env.NEXT_PUBLIC_AGENT_URL ||
    "http://localhost:4022"
  ).replace(/\/$/, "");
}

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ jobId: string }> }
) {
  try {
    await ensureChatSchema();
    const { jobId } = await ctx.params;
    const session = await auth();

    const res = await fetch(`${agentBase()}/v1/agent/jobs/${jobId}`);
    const text = await res.text();
    if (!res.ok) {
      return NextResponse.json(
        { error: text || `Job error ${res.status}` },
        { status: res.status }
      );
    }
    const job = JSON.parse(text) as {
      id: string;
      status?: string;
      step?: string | null;
      artifacts?: unknown[];
      service?: string;
      error?: string | null;
    };

    // Guests can poll jobs they started in this browser session.
    // Logged-in users also sync artifacts into their generation history.
    if (session?.user?.id) {
      const owns = await userOwnsJob(session.user.id, jobId);
      if (owns) {
        await updateGenerationFromJob(session.user.id, jobId, {
          status: job.status,
          step: job.step,
          artifacts: (job.artifacts || []) as never,
        });
      }
    }

    return NextResponse.json(job);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Poll failed" },
      { status: 500 }
    );
  }
}
