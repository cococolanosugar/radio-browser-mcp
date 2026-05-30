---
name: radio-browser
description: Browse and play internet radio stations via Radio-Browser MCP. Use when the user asks to play music/radio, browse stations by genre/country, stop playback, or discover new stations.
tools: mcp__radio__play_station, mcp__radio__browse_radio, mcp__radio__play_by_uuid, mcp__radio__stop, mcp__radio__now_playing, mcp__radio__next_station, mcp__radio__random_station
---

# radio-browser-mcp

Browse and play internet radio stations from Radio-Browser's global directory of 30,000+ stations via MCP.

## When to Use

- User asks to play music, radio, or a stream
- User says "下一首", "next track", "播放电台", "play radio"
- User wants to browse, search, or discover stations by genre/country/language
- User asks what's currently playing

## Available Tools

| Tool | When to Use |
|------|-------------|
| `browse_radio(limit?, tag?, country?, language?)` | User wants to discover stations. Use tag/genre/country filters. |
| `play_station(name)` | User names a station (searches Radio-Browser by name) |
| `play_by_uuid(uuid)` | Play a station found via browse_radio |
| `next_station()` | "下一首" / "next track" |
| `random_station(tag?)` | "随机播放" / random station, optionally by genre |
| `stop()` | User asks to stop/pause playback |
| `now_playing()` | User asks what's playing or wants spectrum |

## Workflows

### "下一首" / "Next track"

1. Call `next_station()` — cycles through top global stations

### "Play some jazz" / "找爵士电台"

1. Call `browse_radio(tag="jazz", limit=10)`
2. Present the list to the user
3. On user selection, call `play_by_uuid(uuid)`

### "Play BBC Radio 1"

1. Call `play_station(name="BBC Radio 1")` — searches Radio-Browser by name

### "What's playing?"

1. Call `now_playing()` — returns title + spectrum visualization

### "Random station"

1. Call `random_station()` — picks from top global stations
2. Or `random_station(tag="rock")` — picks random rock station

## Notes

- All stations come from Radio-Browser (free, no API key, 30k+ stations)
- `play_station` does partial name matching (case-insensitive)
- On Windows, mpv must be in PATH or at `C:\Program Files\MPV Player`
