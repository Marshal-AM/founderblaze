import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { createThread, listThreads } from "@/lib/history";
import { ensureChatSchema } from "@/lib/migrate";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ threads: [], authenticated: false });
  }
  await ensureChatSchema();
  const threads = await listThreads(session.user.id);
  return NextResponse.json({ threads, authenticated: true });
}

export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Sign in required" }, { status: 401 });
  }
  await ensureChatSchema();
  const body = (await req.json().catch(() => ({}))) as { title?: string };
  const thread = await createThread(session.user.id, {
    title: body.title || "New chat",
  });
  return NextResponse.json({ thread });
}
