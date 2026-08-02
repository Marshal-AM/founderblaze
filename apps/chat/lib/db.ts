import { Pool } from "pg";

declare global {
  // eslint-disable-next-line no-var
  var __fbPool: Pool | undefined;
}

export function getPool(): Pool {
  if (!globalThis.__fbPool) {
    const url = process.env.DATABASE_URL;
    if (!url) {
      throw new Error("DATABASE_URL is required for chat auth/history");
    }
    globalThis.__fbPool = new Pool({ connectionString: url, max: 8 });
  }
  return globalThis.__fbPool;
}
