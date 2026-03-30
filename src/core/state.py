"""Global app state — TTS instance, request counters, system metrics."""

from src.tts.engine import KokoroTTS

# App state (set during lifespan)
start_time: float = 0
tts: KokoroTTS | None = None

# Request counters
req_count: int = 0
total_audio_sec: float = 0.0
total_synth_ms: float = 0.0

# CPU monitoring
last_cpu_sample: tuple = (0.0, 0.0)  # (busy, total) from /proc/stat


def track_request(audio_sec: float, synth_ms: float = 0.0):
    """Increment request counters."""
    global req_count, total_audio_sec, total_synth_ms
    req_count += 1
    total_audio_sec += audio_sec
    total_synth_ms += synth_ms


def read_proc_meminfo() -> dict:
    """Read system memory from /proc/meminfo."""
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if parts[0].rstrip(":") in ("MemTotal", "MemAvailable", "MemFree"):
                    info[parts[0].rstrip(":")] = int(parts[1]) * 1024  # kB -> bytes
    except OSError:
        pass
    return info


def read_process_mem() -> dict:
    """Read process memory from /proc/self/status."""
    info = {}
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith(("VmRSS", "VmPeak", "VmSize")):
                    parts = line.split()
                    info[parts[0].rstrip(":")] = int(parts[1]) * 1024  # kB -> bytes
    except OSError:
        pass
    return info


def read_cpu_percent() -> float:
    """Estimate CPU usage % since last sample from /proc/stat."""
    global last_cpu_sample
    try:
        with open("/proc/stat") as f:
            fields = f.readline().split()[1:]  # skip 'cpu' label
        vals = [int(v) for v in fields]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        total = sum(vals)
        prev_busy, prev_total = last_cpu_sample
        d_total = total - prev_total
        d_busy = (total - idle) - prev_busy
        last_cpu_sample = (total - idle, total)
        if d_total == 0:
            return 0.0
        return round(d_busy / d_total * 100, 1)
    except OSError:
        return 0.0
