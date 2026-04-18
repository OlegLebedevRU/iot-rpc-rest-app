"""Entry point: python -m leo4_mcp or leo4-mcp CLI."""
from __future__ import annotations
import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, stream=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="LEO4 MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for SSE transport (default: 8765)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    args = parser.parse_args()

    from .server import mcp

    if args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
