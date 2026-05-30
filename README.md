# radio-browser-mcp ♫

MCP server for Radio-Browser internet radio + Claude Code status line with audio spectrum.

```
♫ BBC Radio 1 ▂▄▆█▇▅▃▂▃▅▇█
```

## Features

- **MCP Server** — control internet radio from Claude Code via natural language
- **Radio-Browser** — browse 30,000+ global stations by popularity, genre, country
- **Auto-start mpv** — no manual `mpv --input-ipc-server` needed
- **Status Line** — real-time now-playing + spectrum visualization
- **Cross-platform** — macOS / Linux / Windows

## Quick Start

```bash
# Install
cd radio-browser-mcp
./install.sh          # macOS / Linux
# .\install.ps1       # Windows PowerShell

# Restart Claude Code, then use:
# "Play some jazz" → Claude calls browse_radio(tag="jazz")
# "下一首" → Claude calls next_station()
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `play_station(name)` | Search Radio-Browser and play by name. |
| `browse_radio(limit, tag, country, language)` | Browse popular stations from Radio-Browser. |
| `play_by_uuid(uuid)` | Play a Radio-Browser station by UUID. |
| `stop()` | Stop playback. |
| `now_playing()` | Get current track + spectrum. |
| `next_station()` | Play next popular station. |
| `random_station(tag?)` | Play random station (optionally by genre). |

## CLI Usage

```bash
# Run MCP server (default, used by Claude Code)
radio-browser-mcp

# Browse popular radio stations
radio-browser-mcp --browse
radio-browser-mcp --browse --tag jazz --limit 5

# Status line output (used by statusLine config)
radio-browser-mcp --status

# Stop
radio-browser-mcp --stop

# Check setup
radio-browser-mcp --check

# Test spectrum visualization
radio-browser-mcp --spectrum
```

## Requirements

- Python 3.10+
- `mcp` package (auto-installed)
- `httpx` package (auto-installed)
- mpv (for playback)
- ffmpeg (for spectrum capture, optional - animated fallback without it)
- pywin32 (Windows only, for named pipe support)

## License

MIT
