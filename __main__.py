"""Entry point for `python -m ticktick_mcp`."""

import os
from ticktick_mcp.server import mcp

transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
port = int(os.environ.get("PORT", "8000"))

if transport == "stdio":
    mcp.run(transport="stdio")
else:
    mcp.run(transport=transport, host="0.0.0.0", port=port)
