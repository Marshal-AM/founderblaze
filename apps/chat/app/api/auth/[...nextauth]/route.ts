import type { NextRequest } from "next/server";
import { handlers } from "@/auth";
import { ensureChatSchema } from "@/lib/migrate";

async function withSchema(
  req: NextRequest,
  handler: (req: NextRequest) => Promise<Response>
): Promise<Response> {
  try {
    await ensureChatSchema();
  } catch (err) {
    console.error("ensureChatSchema failed", err);
    return Response.json(
      { error: "Database schema unavailable" },
      { status: 500 }
    );
  }
  return handler(req);
}

export async function GET(req: NextRequest) {
  return withSchema(req, handlers.GET);
}

export async function POST(req: NextRequest) {
  return withSchema(req, handlers.POST);
}
