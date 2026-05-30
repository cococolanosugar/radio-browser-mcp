# -*- coding: utf-8 -*-
"""
radio-browser-mcp: MCP server for Radio-Browser + Claude Code status line.

Features:
  - Radio-Browser global directory (browse/search by popularity)
  - Auto-start/stop mpv process for playback
  - Query current track info via IPC
  - Audio spectrum visualization (ffmpeg + FFT)
  - Status line output for Claude Code

Cross-platform: macOS / Linux / Windows

Usage:
  radio-browser-mcp                  Run MCP server (stdio transport)
  radio-browser-mcp --status         Print status line (for statusLine config)
  radio-browser-mcp --stop           Stop playback
  radio-browser-mcp --check          Verify setup
  radio-browser-mcp --browse [tag]   Browse popular radio stations
  radio-browser-mcp --spectrum       Test spectrum visualization
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
import httpx

from radio_browser_mcp.spectrum import get_spectrum, cleanup as spectrum_cleanup, find_ffmpeg

# ━━━ Logging (stderr only - stdout is reserved for MCP protocol) ━━━━━━━

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("radio-browser-mcp")

# ━━━ Configuration ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BARS = "▁▂▃▄▅▆▇█"
NUM_BARS = 12
TITLE_MAX = 30
IPC_TIMEOUT = 0.3

SYS = platform.system()
IS_WIN = SYS == "Windows"
IS_MAC = SYS == "Darwin"

STATE_DIR = Path.home() / ".claude"
STATE_FILE = STATE_DIR / "radio-browser-mcp.json"

# ━━━ Radio-Browser API ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RB_API_HOST = "all.api.radio-browser.info"
RB_USER_AGENT = "radio-browser-mcp/0.3.0"
RB_TIMEOUT = 5.0

# ━━━ State Management ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

def _save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

def _clear_state() -> None:
    try:
        STATE_FILE.unlink()
    except FileNotFoundError:
        pass

# ━━━ mpv Process Manager ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_mpv_proc: Optional[subprocess.Popen] = None

def _socket_path() -> str:
    if IS_WIN:
        return r"\\.\pipe\radio-browser-mcp"
    return "/tmp/radio-browser-mcp.sock"

def start_mpv(url: str, name: str = "") -> dict:
    """Start mpv with IPC server. Returns state dict."""
    global _mpv_proc

    stop_mpv()

    sock = _socket_path()

    # Clean stale socket
    if not IS_WIN:
        Path(sock).unlink(missing_ok=True)

    cmd = [
        "mpv",
        f"--input-ipc-server={sock}",
        "--no-terminal",
        "--no-video",
        "--no-audio-display",
        url,
    ]

    # Hide console window on Windows
    startupinfo = None
    if IS_WIN:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    logger.info(f"Starting mpv: {' '.join(cmd)}")

    _mpv_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startupinfo,
    )

    # Wait for socket (max 3 seconds)
    for _ in range(30):
        time.sleep(0.1)
        if IS_WIN or Path(sock).exists():
            break

    state = {
        "socket": sock,
        "pid": _mpv_proc.pid,
        "station": name or _guess_name(url),
        "url": url,
        "started_at": time.time(),
    }
    _save_state(state)

    logger.info(f"mpv started: PID={state['pid']}, station={state['station']}")
    return state

def stop_mpv() -> None:
    """Stop mpv process and clean up."""
    global _mpv_proc

    state = _load_state()

    # Kill by saved PID
    if pid := state.get("pid"):
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
                logger.info(f"Sent SIGTERM to PID {pid}")
        except (ProcessLookupError, OSError, subprocess.SubprocessError):
            pass

    # Kill tracked process
    if _mpv_proc and _mpv_proc.poll() is None:
        try:
            _mpv_proc.terminate()
            _mpv_proc.wait(timeout=2)
        except Exception:
            try:
                _mpv_proc.kill()
            except Exception:
                pass
    _mpv_proc = None

    # Cleanup
    if sock := state.get("socket"):
        Path(sock).unlink(missing_ok=True)

    _clear_state()
    logger.info("mpv stopped")

def _guess_name(url: str) -> str:
    """Extract a short name from URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or url
    for prefix in ("www.", "stream.", "radio.", "listen."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host.split(".")[0].title() if "." in host else host

# ━━━ mpv IPC Client ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _mpv_query(props: list[str]) -> dict[str, object]:
    """Query mpv properties via IPC."""
    state = _load_state()
    sock = state.get("socket", _socket_path())

    if IS_WIN:
        return await _mpv_query_win(sock, props)

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(sock), timeout=IPC_TIMEOUT
        )
    except (OSError, asyncio.TimeoutError, FileNotFoundError):
        return {}

    try:
        for i, prop in enumerate(props):
            cmd = json.dumps({
                "command": ["get_property", prop],
                "request_id": i,
            }) + "\n"
            writer.write(cmd.encode())
        await writer.drain()

        out: dict[str, object] = {}
        for _ in props:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=IPC_TIMEOUT)
                if not line:
                    break
                d = json.loads(line)
                if d.get("error") == "success":
                    idx = d.get("request_id", -1)
                    if 0 <= idx < len(props):
                        out[props[idx]] = d.get("data")
            except (asyncio.TimeoutError, json.JSONDecodeError, KeyError):
                break
        return out
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

async def _mpv_query_win(pipe: str, props: list[str]) -> dict[str, object]:
    """Windows named pipe query."""
    try:
        import win32file  # type: ignore
    except ImportError:
        return {}
    try:
        h = win32file.CreateFile(
            pipe,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None, win32file.OPEN_EXISTING, 0, None,
        )
        out: dict[str, object] = {}
        for i, prop in enumerate(props):
            cmd = json.dumps({
                "command": ["get_property", prop],
                "request_id": i,
            }) + "\n"
            win32file.WriteFile(h, cmd.encode())
            _, data = win32file.ReadFile(h, 4096)
            d = json.loads(data.decode().strip())
            if d.get("error") == "success":
                out[prop] = d.get("data")
        win32file.CloseHandle(h)
        return out
    except Exception:
        return {}

# ━━━ Radio-Browser Helpers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _rb_get(path: str, params: dict | None = None) -> list | dict:
    """GET request to Radio-Browser API. Returns parsed JSON or empty list."""
    url = f"https://{RB_API_HOST}{path}"
    try:
        resp = httpx.get(
            url,
            params=params or {},
            headers={"User-Agent": RB_USER_AGENT},
            timeout=RB_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Radio-Browser request failed: {e}")
        return []

def _report_click(uuid: str) -> None:
    """Report a station click to Radio-Browser (fire-and-forget)."""
    try:
        httpx.get(
            f"https://{RB_API_HOST}/json/url/{uuid}",
            headers={"User-Agent": RB_USER_AGENT},
            timeout=RB_TIMEOUT,
        )
    except Exception:
        pass  # best-effort

def _format_station(s: dict, idx: int) -> str:
    """Format a single station for display."""
    name = s.get("name", "Unknown")
    country = s.get("countrycode", "")
    codec = s.get("codec", "")
    bitrate = s.get("bitrate", 0)
    tags = s.get("tags", "")
    clicks = s.get("clickcount", 0)

    parts = [f"{idx:>2}. {name}"]
    meta = []
    if country:
        meta.append(country)
    if codec and bitrate:
        meta.append(f"{codec} {bitrate}kbps")
    elif codec:
        meta.append(codec)
    if meta:
        parts.append(f" [{', '.join(meta)}]")
    if clicks:
        parts.append(f"  ▶{clicks}")
    if tags:
        short_tags = ", ".join(t.strip() for t in tags.split(",")[:3])
        parts.append(f"  ({short_tags})")
    return "".join(parts)

# ━━━ Status Line ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _bar(v: float) -> str:
    i = int(max(0.0, min(1.0, v)) * (len(BARS) - 1))
    return BARS[i]

def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"

def _query_mpv_sync(props: list[str]) -> dict[str, object]:
    """Synchronous mpv query wrapper."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _mpv_query(props)).result(timeout=IPC_TIMEOUT * 2)
        else:
            return asyncio.run(_mpv_query(props))
    except RuntimeError:
        return asyncio.run(_mpv_query(props))
    except Exception:
        logger.debug("_query_mpv_sync failed", exc_info=True)
        return {}

def get_status_line() -> str:
    """Generate formatted status line for Claude Code."""
    state = _load_state()

    if not state:
        return "♫ idle"

    # Try mpv IPC for live title
    info = _query_mpv_sync(["media-title", "idle-active"])
    if not info:
        pid = state.get("pid")
        if pid and not _pid_alive(pid):
            _clear_state()
            return "♫ idle"
        return f"♫ {state.get('station', 'unknown')}"

    title = info.get("media-title")
    idle = info.get("idle-active", False)

    if idle and not title:
        return "♫ idle"

    title = title or state.get("station", "Unknown")

    levels = get_spectrum(NUM_BARS)
    bars = "".join(_bar(v) for v in levels)

    return f"♫ {_trunc(str(title).strip(), TITLE_MAX)} {bars}"

# ━━━ MCP Server ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

mcp_server = FastMCP("radio-browser-mcp")

@mcp_server.tool()
async def play_station(name: str) -> str:
    """Play a station by name from Radio-Browser global directory.
    Partial name matching is supported (case-insensitive).

    Args:
        name: Station name (e.g. "BBC Radio 1", "jazz fm")
    """
    results = _rb_get("/json/stations/search", {
        "name": name,
        "limit": 10,
        "order": "clickcount",
        "reverse": "true",
        "hidebroken": "true",
    })
    if results and isinstance(results, list) and len(results) > 0:
        station = results[0]
        url = station.get("url_resolved") or station.get("url", "")
        if not url:
            return f"Station has no playable URL: {station.get('name', name)}"
        station_name = station.get("name", name)
        state = start_mpv(url, station_name)
        if uuid := station.get("stationuuid"):
            _report_click(uuid)
        found = len(results)
        return f"♫ Playing: {station_name} ({found} results)\nPID: {state['pid']}"

    return f"Station not found: {name}. Use browse_radio to discover stations."

@mcp_server.tool()
async def stop() -> str:
    """Stop mpv playback."""
    stop_mpv()
    spectrum_cleanup()
    return "♫ Stopped"

@mcp_server.tool()
async def now_playing() -> str:
    """Get current track info with spectrum visualization."""
    return get_status_line()

@mcp_server.tool()
async def browse_radio(
    limit: int = 20,
    tag: str = "",
    country: str = "",
    language: str = "",
) -> str:
    """Browse popular radio stations from Radio-Browser global directory.
    Stations are sorted by popularity (click count).

    Args:
        limit: Number of stations to show (default 20, max 100)
        tag: Filter by genre/tag (e.g. "jazz", "rock", "news", "classical")
        country: Filter by ISO country code (e.g. "US", "GB", "DE", "JP")
        language: Filter by language (e.g. "english", "german", "chinese")
    """
    limit = max(1, min(limit, 100))

    if not tag and not country and not language:
        results = _rb_get(f"/json/stations/topclick/{limit}")
    else:
        params: dict = {
            "order": "clickcount",
            "reverse": "true",
            "hidebroken": "true",
            "limit": str(limit),
        }
        if tag:
            params["tag"] = tag
        if country:
            params["countrycode"] = country
        if language:
            params["language"] = language
        results = _rb_get("/json/stations/search", params)

    if not results or not isinstance(results, list):
        return "No stations found. Check your filters and try again."

    lines = [f"📻 Radio-Browser ({len(results)} stations):\n"]
    for i, s in enumerate(results, 1):
        lines.append(_format_station(s, i))
    lines.append(f"\nUse play_by_uuid to play a station by its UUID.")

    lines.append("\nTop UUIDs:")
    for i, s in enumerate(results[:5], 1):
        name = s.get("name", "?")
        uuid = s.get("stationuuid", "?")
        lines.append(f"  {i}. {name}: {uuid}")

    return "\n".join(lines)

@mcp_server.tool()
async def play_by_uuid(uuid: str) -> str:
    """Play a Radio-Browser station by its UUID (from browse_radio results).
    Automatically reports the click to Radio-Browser.

    Args:
        uuid: Station UUID from browse_radio results
    """
    results = _rb_get(f"/json/stations/byuuid/{uuid}")
    if not results or not isinstance(results, list) or len(results) == 0:
        return f"Station not found: {uuid}"

    station = results[0]
    url = station.get("url_resolved") or station.get("url", "")
    if not url:
        return f"Station has no playable URL: {station.get('name', uuid)}"

    name = station.get("name", "Unknown")
    state = start_mpv(url, name)

    _report_click(uuid)

    country = station.get("countrycode", "")
    codec = station.get("codec", "")
    bitrate = station.get("bitrate", 0)
    meta = f"{codec} {bitrate}kbps" if codec and bitrate else codec
    loc = f" ({country})" if country else ""

    return f"♫ Playing: {name}{loc} [{meta}]\nPID: {state['pid']}"

@mcp_server.tool()
async def next_station() -> str:
    """Play the next popular station from Radio-Browser.

    Cycles through the top global stations. Each call advances to the next one.
    """
    # Use a simple index stored in state
    state = _load_state()
    current_idx = state.get("_browse_idx", -1)

    results = _rb_get("/json/stations/topclick/20")
    if not results or not isinstance(results, list) or len(results) == 0:
        return "No stations available from Radio-Browser."

    next_idx = (current_idx + 1) % len(results)
    station = results[next_idx]
    url = station.get("url_resolved") or station.get("url", "")
    if not url:
        return f"Station has no playable URL: {station.get('name', '?')}"
    name = station.get("name", "Unknown")

    new_state = start_mpv(url, name)
    new_state["_browse_idx"] = next_idx
    _save_state(new_state)

    if uuid := station.get("stationuuid"):
        _report_click(uuid)

    return f"♫ Next: {name} ({next_idx + 1}/{len(results)})"

@mcp_server.tool()
async def random_station(tag: str = "") -> str:
    """Play a random station from Radio-Browser.

    Args:
        tag: Optional genre filter (e.g. "jazz", "rock", "classical", "news").
             If empty, picks from top global stations.
    """
    import random

    if tag:
        results = _rb_get("/json/stations/search", {
            "tag": tag,
            "limit": "100",
            "order": "clickcount",
            "reverse": "true",
            "hidebroken": "true",
        })
    else:
        results = _rb_get("/json/stations/topclick/100")

    if not results or not isinstance(results, list):
        return f"No stations found{'for tag: ' + tag if tag else ''}."

    station = random.choice(results)
    url = station.get("url_resolved") or station.get("url", "")
    if not url:
        return "Random station has no playable URL, try again."
    name = station.get("name", "Unknown")
    start_mpv(url, name)
    if uuid := station.get("stationuuid"):
        _report_click(uuid)

    label = f" [{tag}]" if tag else ""
    return f"♫ Random{name and label}: {name}"

# ━━━ CLI Entry Point ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main() -> None:
    """Main entry point. Routes to CLI or MCP server based on args."""
    args = sys.argv[1:]

    if "--status" in args:
        print(get_status_line())
        return

    if "--stop" in args:
        stop_mpv()
        spectrum_cleanup()
        print("♫ Stopped")
        return

    if "--check" in args:
        _check()
        return

    if "--browse" in args:
        _cli_browse(args)
        return

    if "--spectrum" in args:
        _test_spectrum()
        return

    if "--help" in args or "-h" in args:
        print(_help())
        return

    logger.info("Starting radio-browser-mcp MCP server (stdio transport)")
    mcp_server.run(transport="stdio")

def _cli_browse(args: list[str]) -> None:
    """CLI mode: browse popular radio stations."""
    tag = ""
    limit = 10
    for i, a in enumerate(args):
        if a == "--tag" and i + 1 < len(args):
            tag = args[i + 1]
        if a == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass

    if tag:
        print(f"📻 Top {limit} stations (tag: {tag}):\n")
        results = _rb_get("/json/stations/search", {
            "tag": tag, "limit": str(limit),
            "order": "clickcount", "reverse": "true", "hidebroken": "true",
        })
    else:
        print(f"📻 Top {limit} stations (global):\n")
        results = _rb_get(f"/json/stations/topclick/{limit}")

    if not results or not isinstance(results, list):
        print("  No stations found or API unavailable.")
        return

    for i, s in enumerate(results, 1):
        print(_format_station(s, i))

def _check() -> None:
    """Verify setup."""
    print("radio-browser-mcp setup check\n")

    print(f"  Platform:  {SYS}")
    print(f"  Python:    {sys.version.split()[0]}")
    print(f"  State dir: {STATE_DIR}")
    print()

    mpv = shutil.which("mpv")
    if mpv:
        print(f"  mpv:       ✓ {mpv}")
    else:
        print(f"  mpv:       ✗ not found")
        if IS_MAC:
            print(f"             Install: brew install mpv")
        elif IS_WIN:
            print(f"             Install: scoop install mpv")
        else:
            print(f"             Install: sudo apt install mpv")
    print()

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        print(f"  ffmpeg:    ✓ {ffmpeg} (real spectrum)")
    else:
        print(f"  ffmpeg:    ✗ not found (animated fallback)")
        if IS_MAC:
            print(f"             Install: brew install ffmpeg")
        elif IS_WIN:
            print(f"             Install: scoop install ffmpeg")
        else:
            print(f"             Install: sudo apt install ffmpeg")
    print()

    try:
        stats = _rb_get("/json/stats")
        if isinstance(stats, dict) and stats.get("stations"):
            print(f"  Radio-Browser: ✓ Connected ({stats['stations']} stations)")
        else:
            print(f"  Radio-Browser: ⚠ No stats returned")
    except Exception:
        print(f"  Radio-Browser: ✗ unreachable")
    print()

    state = _load_state()
    if state:
        pid = state.get("pid", "?")
        alive = _pid_alive(pid)
        status = "✓ running" if alive else "✗ dead"
        print(f"  Session:   {status}")
        print(f"             Station: {state.get('station', '?')}")
        print(f"             Socket:  {state.get('socket', '?')}")
        print(f"             PID:     {pid}")
    else:
        print(f"  Session:   (none)")
    print()

    levels = get_spectrum(NUM_BARS)
    bars = "".join(_bar(v) for v in levels)
    print(f"  Preview:   ♫ Demo FM {bars}")
    print()

    print(f"  Claude Code config (~/.claude.json):")
    print(f'  "mcpServers": {{ "radio": {{ "command": "radio-browser-mcp" }} }}')

def _test_spectrum() -> None:
    """Test spectrum visualization."""
    print("Spectrum test (Ctrl+C to quit)\n")

    try:
        while True:
            levels = get_spectrum(NUM_BARS)
            bar_str = "".join(_bar(v) for v in levels)
            print(f"\r{bar_str}", end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n\nDone.")
    finally:
        spectrum_cleanup()

def _pid_alive(pid: int) -> bool:
    try:
        if IS_WIN:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True
            )
            return str(pid) in r.stdout
        else:
            os.kill(pid, 0)
            return True
    except (ProcessLookupError, OSError, subprocess.SubprocessError):
        return False

def _help() -> str:
    return """radio-browser-mcp: MCP server for Radio-Browser + Claude Code status line

USAGE:
  radio-browser-mcp                  Run MCP server (stdio transport)
  radio-browser-mcp --status         Print status line (for statusLine config)
  radio-browser-mcp --stop           Stop playback
  radio-browser-mcp --check          Verify setup
  radio-browser-mcp --browse [tag]   Browse popular radio stations
  radio-browser-mcp --spectrum       Test spectrum visualization

OPTIONS:
  --tag <genre>            Filter --browse by tag (e.g. jazz, rock, news)
  --limit <n>              Number of stations (default 10)
  --help, -h               Show this help

EXAMPLES:
  radio-browser-mcp --browse
  radio-browser-mcp --browse --tag jazz --limit 5
  radio-browser-mcp --status
"""

# ━━━ Entry Point ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    main()
