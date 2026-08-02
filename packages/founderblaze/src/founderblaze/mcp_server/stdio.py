from __future__ import annotations

import asyncio
import logging

from mcp.server.stdio import stdio_server

from founderblaze.core.logging import setup_logging
from founderblaze.mcp_server.server import create_mcp_server

log = logging.getLogger("founderblaze.mcp_server.stdio")


async def _run() -> None:
    setup_logging()
    server = create_mcp_server()
    log.info("FounderBlaze MCP server starting (stdio)")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
