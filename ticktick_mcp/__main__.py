"""Entry point for `python -m ticktick_mcp`."""

import os
from ticktick_mcp.server import mcp

transport = os.environ.get("MCP_TRANSPORT", "streamable-http")

if transport == "streamable-http":
    mcp.run(transport="streamable-http")
else:
    port = int(os.environ.get("PORT", "8000"))
    mcp.run(transport=transport, host="0.0.0.0", port=port)
