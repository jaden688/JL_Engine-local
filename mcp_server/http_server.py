from mcp_server.server import mcp

if __name__ == "__main__":
    # FastMCP.run only takes transport and mount_path. 
    # It defaults to localhost:8000 when using streamable-http.
    mcp.run(
        transport="streamable-http"
    )
