"""
spectrum: Cross-platform audio spectrum capture.

Uses system audio loopback + FFT to generate spectrum data.
No external dependencies (no cava needed).

Platforms:
  - macOS:  AVFoundation loopback via ffmpeg subprocess
  - Linux:  PulseAudio monitor via ffmpeg subprocess
  - Windows: WASAPI loopback via ffmpeg subprocess

Falls back to animated placeholder if audio capture fails.
"""

from __future__ import annotations

import math
import platform
import shutil
import struct
import subprocess
import time
from typing import Optional

# ━━━ Config ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NUM_BARS = 12
SAMPLE_RATE = 44100
CHUNK_MS = 50  # 50ms per frame = 20fps
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000
CACHE_TTL = 0.1  # 100ms cache
READ_TIMEOUT = 0.2  # Max seconds to wait for audio data

# Frequency bands (Hz) - tuned for music visualization
BAND_EDGES = [
    20, 60, 150, 300, 500, 800, 1200, 2000, 3500, 5000, 8000, 12000, 20000
]

# ━━━ State ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_capture_proc: Optional[subprocess.Popen] = None
_cached: tuple[float, list[float]] | None = None

# ━━━ Platform Detection ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYS = platform.system()
IS_WIN = SYS == "Windows"
IS_MAC = SYS == "Darwin"

# ━━━ Audio Capture ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def find_ffmpeg() -> Optional[str]:
    """Find ffmpeg binary."""
    return shutil.which("ffmpeg")

def _get_audio_device() -> Optional[str]:
    """Get system audio loopback device for ffmpeg."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None

    try:
        if IS_MAC:
            # macOS: use avfoundation with screen capture (includes system audio)
            # Device "1:none" captures screen audio, ":none" is audio-only
            # Note: device index may vary; "1" is usually the default screen
            return "avfoundation:1:none"
        elif IS_WIN:
            # Windows: use dshow with virtual audio cable or stereo mix
            result = subprocess.run(
                [ffmpeg, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                capture_output=True, text=True, timeout=5
            )
            # Look for Stereo Mix or similar
            for line in result.stderr.split("\n"):
                if "stereo mix" in line.lower() or "loopback" in line.lower():
                    if '"' in line:
                        name = line.split('"')[1]
                        return f"dshow:audio={name}"
            # Fallback: try default audio
            return "dshow:audio=virtual-audio-capturer"
        else:
            # Linux: try PipeWire first, then PulseAudio, then ALSA
            # PipeWire (modern systems)
            try:
                result = subprocess.run(
                    ["wpctl", "status"],
                    capture_output=True, text=True, timeout=3
                )
                if result.returncode == 0 and "Audio" in result.stdout:
                    # Use PipeWire's default source
                    return "pipewire:default"
            except FileNotFoundError:
                pass

            # PulseAudio
            try:
                result = subprocess.run(
                    ["pactl", "list", "short", "sources"],
                    capture_output=True, text=True, timeout=3
                )
                for line in result.stdout.split("\n"):
                    if ".monitor" in line:
                        name = line.split("\t")[1]
                        return f"pulse:{name}"
                # Fallback to default
                return "pulse:default"
            except FileNotFoundError:
                pass

            # ALSA fallback
            return "alsa:default"
    except Exception:
        return None

def _start_capture() -> Optional[subprocess.Popen]:
    """Start ffmpeg audio capture process."""
    global _capture_proc

    if _capture_proc and _capture_proc.poll() is None:
        return _capture_proc

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None

    device = _get_audio_device()
    if not device:
        return None

    fmt, source = device.split(":", 1)

    cmd = [
        ffmpeg,
        "-f", fmt,
        "-i", source,
        "-ac", "1",           # mono
        "-ar", str(SAMPLE_RATE),
        "-f", "s16le",        # raw PCM
        "-acodec", "pcm_s16le",
        "-loglevel", "error",
        "-"                   # stdout
    ]

    try:
        _capture_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=CHUNK_SAMPLES * 2,  # 2 bytes per sample
        )
        return _capture_proc
    except Exception:
        return None

def _stop_capture() -> None:
    """Stop ffmpeg capture."""
    global _capture_proc
    if _capture_proc:
        try:
            _capture_proc.terminate()
            _capture_proc.wait(timeout=2)
        except Exception:
            try:
                _capture_proc.kill()
            except Exception:
                pass
    _capture_proc = None

# ━━━ FFT Processing (Cooley-Tukey) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _fft_fast(data: list[complex]) -> list[complex]:
    """Cooley-Tukey FFT (radix-2). Input length must be power of 2."""
    n = len(data)
    if n <= 1:
        return data

    # Bit-reversal permutation
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            data[i], data[j] = data[j], data[i]

    # Cooley-Tukey butterfly
    length = 2
    while length <= n:
        angle = -2 * math.pi / length
        w = complex(math.cos(angle), math.sin(angle))
        for i in range(0, n, length):
            wn = 1+0j
            for j in range(length // 2):
                u = data[i + j]
                v = data[i + j + length // 2] * wn
                data[i + j] = u + v
                data[i + j + length // 2] = u - v
                wn *= w
        length *= 2

    return data

def _fft_bands(samples: list[float], n_bands: int = NUM_BARS) -> list[float]:
    """Compute frequency bands using fast FFT."""
    n = len(samples)
    if n == 0:
        return [0.0] * n_bands

    # Pad to power of 2
    nfft = 1
    while nfft < n:
        nfft *= 2
    nfft = min(nfft, 2048)  # Cap at 2048 for speed

    # Prepare complex input
    data = [complex(s, 0) for s in samples[:nfft]]
    while len(data) < nfft:
        data.append(0+0j)

    # FFT
    spectrum = _fft_fast(data)

    # Magnitudes (only first half is useful)
    magnitudes = []
    for k in range(nfft // 2):
        freq = k * SAMPLE_RATE / nfft
        if freq > 20000:
            break
        mag = abs(spectrum[k]) / nfft
        magnitudes.append((freq, mag))

    if not magnitudes:
        return [0.0] * n_bands

    # Map to frequency bands
    bands = []
    for i in range(n_bands):
        lo = BAND_EDGES[i] if i < len(BAND_EDGES) else 20
        hi = BAND_EDGES[i + 1] if i + 1 < len(BAND_EDGES) else 20000

        band_energy = 0.0
        count = 0
        for freq, mag in magnitudes:
            if lo <= freq < hi:
                band_energy += mag
                count += 1

        if count > 0:
            band_energy /= count
        bands.append(band_energy)

    # Normalize with sqrt for better visual dynamics
    max_energy = max(bands) if bands else 1.0
    if max_energy > 0:
        bands = [min(1.0, b / max_energy ** 0.5) for b in bands]

    return bands

# ━━━ Audio Reading ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _read_chunk(proc: subprocess.Popen) -> Optional[list[float]]:
    """Read a chunk of audio samples from ffmpeg (non-blocking with timeout)."""
    bytes_needed = CHUNK_SAMPLES * 2  # 16-bit = 2 bytes per sample

    # Use select for non-blocking read on Unix, fallback to blocking on Windows
    if not IS_WIN:
        import select
        ready, _, _ = select.select([proc.stdout], [], [], READ_TIMEOUT)
        if not ready:
            return None

    data = b""
    deadline = time.time() + READ_TIMEOUT
    while len(data) < bytes_needed:
        if time.time() > deadline:
            return None  # Timeout
        chunk = proc.stdout.read(bytes_needed - len(data))
        if not chunk:
            return None
        data += chunk

    # Convert to float samples
    samples = []
    for i in range(0, len(data), 2):
        if i + 1 < len(data):
            sample = struct.unpack('<h', data[i:i+2])[0]
            samples.append(sample / 32768.0)

    return samples

# ━━━ Public API ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_spectrum(n: int = NUM_BARS) -> list[float]:
    """Get current audio spectrum levels (0.0-1.0).

    Tries real audio capture first, falls back to animated placeholder.
    """
    global _cached

    now = time.time()
    if _cached and (now - _cached[0]) < CACHE_TTL:
        return _cached[1]

    # Try real capture
    proc = _start_capture()
    if proc and proc.poll() is None:
        samples = _read_chunk(proc)
        if samples:
            levels = _fft_bands(samples, n)
            # Smooth with previous values
            if _cached and len(_cached[1]) == len(levels):
                prev = _cached[1]
                levels = [levels[i] * 0.6 + prev[i] * 0.4 for i in range(len(levels))]
            _cached = (now, levels)
            return levels

    # Fallback: animated placeholder
    levels = _animate(n)
    _cached = (now, levels)
    return levels

def _animate(n: int) -> list[float]:
    """Organic animated spectrum (overlapping sine waves)."""
    t = time.time()
    out = []
    for i in range(n):
        v = (
            math.sin(t * 2.5 + i * 0.6)
            + math.sin(t * 1.7 + i * 1.2) * 0.5
            + math.sin(t * 3.1 + i * 0.3) * 0.3
            + 1.5
        ) / 3.5
        out.append(max(0.1, min(1.0, v)))
    return out

def cleanup() -> None:
    """Stop audio capture."""
    _stop_capture()

# ━━━ Test ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    BARS = "▁▂▃▄▅▆▇█"

    print("Spectrum test (Ctrl+C to quit)")
    print(f"Platform: {SYS}")
    print(f"ffmpeg: {find_ffmpeg() or 'not found'}")
    print()

    try:
        while True:
            levels = get_spectrum()
            bar_str = "".join(BARS[int(max(0, min(1, v)) * (len(BARS) - 1))] for v in levels)
            print(f"\r{bar_str}", end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        cleanup()
