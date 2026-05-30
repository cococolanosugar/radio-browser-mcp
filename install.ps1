# ─────────────────────────────────────────────────────────────────────────
# radio-browser-mcp one-click installer (Windows PowerShell)
# Installs the package + configures Claude Code settings
# ─────────────────────────────────────────────────────────────────────────
#Requires -Version 5.1

param(
    [switch]$SkipConfig
)

$ErrorActionPreference = "Stop"

function Write-Ok($msg)   { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  ✗ $msg" -ForegroundColor Red }
function Write-Step($msg) { Write-Host "`n$msg" -ForegroundColor Cyan }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = $ScriptDir
$SettingsFile = Join-Path $env:USERPROFILE ".claude\settings.json"
$ClaudeJsonFile = Join-Path $env:USERPROFILE ".claude.json"

Write-Host "♫ radio-browser-mcp installer" -ForegroundColor Cyan
Write-Host

# ─── Check Python ───────────────────────────────────────────────────────

$Python = $null
foreach ($cmd in @("python3", "python", "py")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $Python = $cmd
        break
    }
}

if (-not $Python) {
    Write-Err "Python not found"
    Write-Host "Install Python 3.10+ from https://python.org"
    exit 1
}

$PyVersion = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Ok "Python: $Python $PyVersion"

# ─── Install package ────────────────────────────────────────────────────

Write-Step "Installing radio-browser-mcp..."

Push-Location $ScriptDir
try {
    & $Python -m pip install -e . --quiet 2>$null
    Write-Ok "Installed (editable mode)"
} catch {
    try {
        & $Python -m pip install . --quiet 2>$null
        Write-Ok "Installed"
    } catch {
        try {
            & $Python -m pip install -e . --user --quiet 2>$null
            Write-Ok "Installed (user mode)"
        } catch {
            Write-Err "pip install failed"
            Write-Host "Try: $Python -m pip install -e $ScriptDir"
            exit 1
        }
    }
}
finally {
    Pop-Location
}

# Verify command
$Cmd = "radio-browser-mcp"
if (-not (Get-Command $Cmd -ErrorAction SilentlyContinue)) {
    $Cmd = "$Python -m radio_browser_mcp.server"
    Write-Warn "radio-browser-mcp not on PATH, using '$Cmd'"
}

# ─── Configure Claude Code ──────────────────────────────────────────────

if (-not $SkipConfig) {
    Write-Step "Configuring Claude Code..."

    # --- MCP servers go in ~/.claude.json ---
    $ClaudeJson = @{}
    if (Test-Path $ClaudeJsonFile) {
        try {
            $ClaudeJson = Get-Content $ClaudeJsonFile -Raw | ConvertFrom-Json -AsHashtable
        } catch {
            $ClaudeJson = @{}
        }
    }
    if (-not $ClaudeJson.mcpServers) {
        $ClaudeJson.mcpServers = @{}
    }
    # Detect mpv path
    $MpvPath = ""
    if (Get-Command mpv -ErrorAction SilentlyContinue) {
        $MpvPath = Split-Path -Parent (Get-Command mpv | Select-Object -ExpandProperty Source)
    } elseif (Test-Path "C:\Program Files\MPV Player\mpv.exe") {
        $MpvPath = "C:\Program Files\MPV Player"
    }
    if ($MpvPath) {
        Write-Ok "mpv path: $MpvPath"
    }

    # Build env with PATH
    $EnvVars = @{ PYTHONIOENCODING = "utf-8" }
    if ($MpvPath) {
        $EnvVars["PATH"] = "$MpvPath;$env:PATH"
    }

    $ClaudeJson.mcpServers.radio = @{
        type    = "stdio"
        command = $Cmd.Split(" ")[0]
        args    = @($Cmd.Split(" ")[1..99] | Where-Object { $_ })
        env     = $EnvVars
    }
    $ClaudeJson | ConvertTo-Json -Depth 10 | Set-Content $ClaudeJsonFile -Encoding UTF8
    Write-Ok "Updated $ClaudeJsonFile (mcpServers.radio)"

    # --- statusLine: create ps1 script in ~/.claude/ ---
    $StatusScript = Join-Path $env:USERPROFILE ".claude\statusline.ps1"
    $StatusDir = Split-Path -Parent $StatusScript
    if (-not (Test-Path $StatusDir)) {
        New-Item -ItemType Directory -Path $StatusDir -Force | Out-Null
    }

    # Build script content
    $ScriptLines = @()
    $ScriptLines += '$env:PYTHONIOENCODING = "utf-8"'
    if ($MpvPath) {
        $ScriptLines += "`$env:PATH = `"$MpvPath;`" + `$env:PATH"
    }
    $ScriptLines += "& `"$($Cmd.Split(" ")[0])`" $($Cmd.Split(" ")[1..99] | Where-Object { $_ }) --status"
    $ScriptLines -join "`n" | Set-Content $StatusScript -Encoding UTF8
    Write-Ok "Created $StatusScript"

    # --- Update settings.json with statusLine ---
    $SettingsFile = Join-Path $env:USERPROFILE ".claude\settings.json"
    $Settings = @{}
    if (Test-Path $SettingsFile) {
        try {
            $Settings = Get-Content $SettingsFile -Raw | ConvertFrom-Json -AsHashtable
        } catch {
            $Settings = @{}
        }
    }
    $Settings.statusLine = @{
        type    = "command"
        command = 'powershell -ExecutionPolicy Bypass -File "$HOME\.claude\statusline.ps1"'
    }
    $Settings | ConvertTo-Json -Depth 10 | Set-Content $SettingsFile -Encoding UTF8
    Write-Ok "Updated $SettingsFile (statusLine)"

    # --- Install skill file ---
    $SkillSrc = Join-Path $ProjectDir "skill\radio-browser.md"
    $SkillDst = Join-Path $env:USERPROFILE ".claude\skills\radio-browser\SKILL.md"
    if (Test-Path $SkillSrc) {
        $SkillDir = Split-Path -Parent $SkillDst
        if (-not (Test-Path $SkillDir)) {
            New-Item -ItemType Directory -Path $SkillDir -Force | Out-Null
        }
        Copy-Item $SkillSrc $SkillDst -Force
        Write-Ok "Installed skill: $SkillDst"
    }
}

# ─── Check mpv ──────────────────────────────────────────────────────────

Write-Step "Checking dependencies..."

if (Get-Command mpv -ErrorAction SilentlyContinue) {
    Write-Ok "mpv: $(Get-Command mpv | Select-Object -ExpandProperty Source)"
} else {
    Write-Warn "mpv: not found"
    Write-Host "             Install: scoop install mpv" -ForegroundColor Cyan
    Write-Host "             Or:      choco install mpv" -ForegroundColor Cyan
}

# ─── Check ffmpeg ───────────────────────────────────────────────────────

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Ok "ffmpeg: $(Get-Command ffmpeg | Select-Object -ExpandProperty Source) (real spectrum)"
} else {
    Write-Warn "ffmpeg: not found (animated fallback)"
    Write-Host "             Install: scoop install ffmpeg" -ForegroundColor Cyan
    Write-Host "             Or:      choco install ffmpeg" -ForegroundColor Cyan
}

# ─── Done ────────────────────────────────────────────────────────────────

Write-Host
Write-Host "✓ Setup complete!" -ForegroundColor Green
Write-Host
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Restart Claude Code"
Write-Host "  2. Say 'play radio' or 'browse jazz stations' in Claude Code"
Write-Host
Write-Host "CLI usage:" -ForegroundColor Cyan
Write-Host "  $Cmd --browse"
Write-Host "  $Cmd --browse --tag jazz --limit 5"
Write-Host "  $Cmd --status"
Write-Host "  $Cmd --stop"
Write-Host "  $Cmd --check"
