# radio-browser-mcp

MCP server for Radio-Browser internet radio + Claude Code status line with audio spectrum.

## Quick Reference

```
cd radio-browser-mcp
run server:    PYTHONIOENCODING=utf-8 radio-browser-mcp --browse --limit 20
check:         PYTHONIOENCODING=utf-8 radio-browser-mcp --check
```

## Architecture

- **server.py** — MCP server (FastMCP), mpv process manager, Radio-Browser API client
- **spectrum.py** — Audio spectrum visualization (ffmpeg + FFT)
- **State file** — `~/.claude/radio-browser-mcp.json` (current session)

## MCP Tools (7 total)

| Tool | Args | Description |
|------|------|-------------|
| `play_station` | name | Search Radio-Browser and play by name. |
| `browse_radio` | limit?, tag?, country?, language? | Browse popular stations from Radio-Browser. |
| `play_by_uuid` | uuid | Play Radio-Browser station by UUID. |
| `stop` | — | Stop playback. |
| `now_playing` | — | Get current track + spectrum. |
| `next_station` | — | Play next popular station. |
| `random_station` | tag? | Play random station (optionally by genre). |

## Radio-Browser API

- Endpoint: `https://all.api.radio-browser.info`
- Browse top stations: `GET /json/stations/topclick/{limit}`
- Search: `GET /json/stations/search?tag=&countrycode=&language=&limit=`
- By UUID: `GET /json/stations/byuuid/{uuid}`
- Click report: `GET /json/url/{uuid}` (follows API guidelines)

## Windows Notes

- **mpv path**: `C:\Program Files\MPV Player` (not in PATH by default)
- **Python encoding**: Always use `PYTHONIOENCODING=utf-8` to avoid GBK emoji errors
- **Named pipe**: Windows uses `\\.\pipe\radio-browser-mcp` (Unix uses `/tmp/radio-browser-mcp.sock`)

## MCP Server Configuration

MCP servers 在 `~/.claude.json` 中配置（与 codegraph 等其他 MCP 服务器一起）：

```json
{
  "mcpServers": {
    "radio": {
      "type": "stdio",
      "command": "radio-browser-mcp",
      "args": [],
      "env": {"PYTHONIOENCODING": "utf-8"}
    }
  }
}
```

statusLine 在 `~/.claude/settings.json` 中配置，通过 PowerShell 脚本执行：

```json
{
  "statusLine": {
    "type": "command",
    "command": "powershell -ExecutionPolicy Bypass -File \"$HOME\\.claude\\statusline.ps1\""
  }
}
```

`~/.claude/statusline.ps1` 脚本内容：
```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:PATH = "C:\Program Files\MPV Player;" + $env:PATH
radio-browser-mcp --status
```

## CLI Commands

```
radio-browser-mcp                    # MCP server mode (stdio)
radio-browser-mcp --stop             # Stop playback
radio-browser-mcp --browse           # Browse top stations
radio-browser-mcp --browse --tag jazz --limit 5
radio-browser-mcp --status           # Status line output
radio-browser-mcp --check            # Verify setup
radio-browser-mcp --spectrum         # Test spectrum visualization
```

## Dependencies

- Python 3.10+
- `mcp` (MCP protocol)
- `httpx` (HTTP client for Radio-Browser)
- `pywin32` (Windows only)
- mpv (system dependency, for playback)
- ffmpeg (optional, for real spectrum capture)
