import { NextResponse } from "next/server";
import { randomUUID } from "crypto";
import bcrypt from "bcryptjs";
import { getPool } from "@/lib/db";
import { ensureChatSchema } from "@/lib/migrate";

export async function POST(req: Request) {
  try {
    await ensureChatSchema();
    const body = (await req.json()) as {
      email?: string;
      password?: string;
      name?: string;
    };
    const email = String(body.email || "")
      .trim()
      .toLowerCase();
    const password = String(body.password || "");
    const name = String(body.name || "").trim() || email.split("@")[0];

    if (!email || !email.includes("@")) {
      return NextResponse.json({ error: "Valid email required" }, { status: 400 });
    }
    if (password.length < 8) {
      return NextResponse.json(
        { error: "Password must be at least 8 characters" },
        { status: 400 }
      );
    }

    const pool = getPool();
    const existing = await pool.query(
      `SELECT id FROM users WHERE lower(email) = $1 LIMIT 1`,
      [email]
    );
    if (existing.rows.length > 0) {
      return NextResponse.json(
        { error: "An account with this email already exists" },
        { status: 409 }
      );
    }

    const id = randomUUID();
    const hash = await bcrypt.hash(password, 12);
    await pool.query(
      `INSERT INTO users (id, name, email, password_hash)
       VALUES ($1, $2, $3, $4)`,
      [id, name, email, hash]
    );

    return NextResponse.json({ ok: true, user: { id, email, name } });
  } catch (err) {
    console.error("register failed", err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Register failed" },
      { status: 500 }
    );
  }
}
