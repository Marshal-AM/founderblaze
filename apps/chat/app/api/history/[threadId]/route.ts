import { NextResponse } from "next/server";
import { auth } from "@/auth";
import {
  getThread,
  listMessages,
  listThreadGenerations,
} from "@/lib/history";
import { ensureChatSchema } from "@/lib/migrate";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ threadId: string }> }
) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Sign in required" }, { status: 401 });
  }
  await ensureChatSchema();
  const { threadId } = await ctx.params;
  const thread = await getThread(session.user.id, threadId);
  if (!thread) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  const [messages, generations] = await Promise.all([
    listMessages(session.user.id, threadId),
    listThreadGenerations(session.user.id, threadId),
  ]);
  return NextResponse.json({ thread, messages, generations });
}
