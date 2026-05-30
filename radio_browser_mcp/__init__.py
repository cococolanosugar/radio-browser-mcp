# -*- coding: utf-8 -*-
"""radio-browser-mcp: MCP server for Radio-Browser + Claude Code status line."""

__version__ = "0.3.0"

from radio_browser_mcp.server import main, mcp_server, get_status_line
from radio_browser_mcp.spectrum import get_spectrum, cleanup, find_ffmpeg

__all__ = [
    "main",
    "mcp_server",
    "get_status_line",
    "get_spectrum",
    "cleanup",
    "find_ffmpeg",
]
