"""Entry point for `python -m ticktick_mcp`."""

import os
port = int(os.environ.get("PORT", 8000))

transport = os.environ.get("MCP_TRANSPORT", "stdio")

if transport == "stdio":
    mcp.run(transport="stdio")
else:
    port = int(os.environ.get("PORT", "8000"))
    mcp.run(transport=transport, host="0.0.0.0", port=port)
