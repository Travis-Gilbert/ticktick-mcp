FROM python:3.12-slim

WORKDIR /app

# Copy backend code
COPY backend/ ./backend/

# Install dependencies
RUN pip install --no-cache-dir mcp httpx python-dotenv pydantic fastmcp

# Set the working directory to backend
WORKDIR /app/backend

# Railway injects PORT as an env var
ENV PORT=8000

# Start the MCP server
CMD ["python", "-m", "ticktick_mcp"]
