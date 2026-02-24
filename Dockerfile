cat > Dockerfile << 'EOF'
FROM python:3.12-slim

WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY ticktick_mcp/ ./ticktick_mcp/

# Install dependencies
RUN pip install --no-cache-dir .

# Railway injects PORT as an env var
ENV PORT=8000
ENV MCP_TRANSPORT=sse

# Start the MCP server
CMD ["python", "-m", "ticktick_mcp"]
EOF
