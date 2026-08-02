import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { listAssets } from "@/lib/history";
import { ensureChatSchema } from "@/lib/migrate";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ assets: [], authenticated: false });
  }
  await ensureChatSchema();
  const assets = await listAssets(session.user.id);
  return NextResponse.json({ assets, authenticated: true });
}
