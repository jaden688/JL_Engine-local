# ── SparkByte MCP Server — standalone container ───────────────────────────────
# Registry: jaden688/sparkbyte-mcp
# Runs the MCP server only (no Julia engine).
# The engine lives at SPARKBYTE_WS (default ws://host.docker.internal:8081).
#
# Build:
#   docker build -t jaden688/sparkbyte-mcp:latest -f mcp_server/Dockerfile .
#
# Run (stdio):
#   docker run --rm -i jaden688/sparkbyte-mcp:latest
#
# Run (SSE, pointing at host engine):
#   docker run --rm -p 8083:8083 \
#     -e MCP_TRANSPORT=sse \
#     -e SPARKBYTE_WS=ws://host.docker.internal:8081 \
#     -e MCP_ALLOW_REMOTE_WS=1 \
#     jaden688/sparkbyte-mcp:latest

FROM python:3.12-slim

LABEL org.opencontainers.image.title="SparkByte MCP Server" \
      org.opencontainers.image.description="Standalone MCP bridge for JL_Engine-SB.Omni" \
      org.opencontainers.image.source="https://github.com/jaden688/JL_Engine-SB.Omni" \
      org.opencontainers.image.authors="jaden688"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    # MCP defaults — override at runtime
    MCP_TRANSPORT=stdio \
    MCP_PORT=8083 \
    MCP_BIND=0.0.0.0 \
    SPARKBYTE_WS=ws://host.docker.internal:8081 \
    MCP_ALLOW_REMOTE_WS=1 \
    MCP_WS_CONCURRENCY=4 \
    MCP_MAX_RESPONSE_BYTES=60000

WORKDIR /app

# Install deps into a venv for layer-cache friendliness
RUN python -m venv /opt/venv
COPY mcp_server/requirements.txt ./mcp_server/requirements.txt
RUN pip install --no-cache-dir -r mcp_server/requirements.txt

# Copy only what the MCP server actually needs
COPY mcp_server/ ./mcp_server/
COPY sparkbyte_memory.db* ./
COPY dynamic_tools_registry.json* ./
# Julian quarry (optional — server handles missing file gracefully)
COPY JulianMetaMorph/ ./JulianMetaMorph/

# Non-root user
RUN useradd -m -u 1001 mcp && chown -R mcp:mcp /app
USER mcp

EXPOSE 8083

HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "\
import urllib.request, os; \
port = os.environ.get('MCP_PORT', '8083'); \
urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=4).read()" \
    || exit 1

# stdio by default; set MCP_TRANSPORT=sse for HTTP mode
CMD ["python", "-m", "mcp_server.server"]
