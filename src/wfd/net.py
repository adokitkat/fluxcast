import shutil
import subprocess
from typing import Optional

from .config import WFDMediaConfig
from .encoding import _vbv_bufsize, _x264_threads
from .modes import _h264_level_for_mode
from .proc import _run


def _safe_source_port(requested: int, sink_port: int, sink_rtcp_port: int = 0) -> int:
    blocked = {sink_port}
    if sink_rtcp_port:
        blocked.add(sink_rtcp_port)
    else:
        blocked.add(sink_port + 1)

    port = requested
    if port % 2:
        port += 1
    while port in blocked or port + 1 in blocked:
        port += 2
    return port

def _rtp_url(tv_ip: str, sink_port: int, source_port: int, local_ip: str) -> str:
    # Bind both RTP and RTCP to the ports advertised in the RTSP SETUP reply.
    # ffmpeg's pkt_size is the whole UDP payload, including the 12-byte RTP
    # header. WFD receivers expect seven 188-byte TS packets per RTP payload:
    # 12 + (7 * 188) = 1328 bytes.
    return (
        f"rtp://{tv_ip}:{sink_port}"
        f"?localaddr={local_ip}"
        f"&local_rtpport={source_port}"
        f"&local_rtcpport={source_port + 1}"
        "&pkt_size=1328"
    )

def _interface_for_ip(local_ip: str) -> Optional[str]:
    if not shutil.which("ip"):
        return None
    try:
        result = _run(["ip", "-o", "-4", "addr", "show"], timeout=2.0)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    needle = f" {local_ip}/"
    for line in result.stdout.splitlines():
        if needle not in line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            return parts[1].split("@", 1)[0]
    return None

def _netdev_tx_bytes(interface: Optional[str]) -> Optional[int]:
    if not interface:
        return None
    try:
        with open("/proc/net/dev", "r", encoding="utf-8", errors="replace") as file:
            lines = file.read().splitlines()
    except OSError:
        return None

    prefix = interface + ":"
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        _, _, counters = stripped.partition(":")
        fields = counters.split()
        if len(fields) >= 16:
            try:
                return int(fields[8])
            except ValueError:
                return None
    return None

def _ffmpeg_sender_args(show_stats: bool = False) -> list[str]:
    args = [
        "ffmpeg", "-hide_banner", "-y",
        "-loglevel", "warning",
    ]
    if show_stats:
        args.append("-stats")
    return args


_ffmpeg_h264_encoder_cache: Optional[str] = None

def _ffmpeg_h264_encoder() -> str:
    """libx264 when ffmpeg has it, else libopenh264 when it has that.

    Fedora's ffmpeg-free has no libx264 but does have libopenh264, backed by
    Cisco's OpenH264 from the default-enabled fedora-cisco-openh264 repo. If
    the encoder list cannot be read, this stays on libx264 as before.
    """
    global _ffmpeg_h264_encoder_cache
    if _ffmpeg_h264_encoder_cache is not None:
        return _ffmpeg_h264_encoder_cache
    encoders: set[str] = set()
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        try:
            output = _run([ffmpeg, "-hide_banner", "-encoders"]).stdout
        except (OSError, subprocess.TimeoutExpired):
            output = ""
        for line in output.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0].startswith("V"):
                encoders.add(fields[1])
    if "libx264" not in encoders and "libopenh264" in encoders:
        _ffmpeg_h264_encoder_cache = "libopenh264"
    else:
        _ffmpeg_h264_encoder_cache = "libx264"
    return _ffmpeg_h264_encoder_cache

def _ffmpeg_h264_args(config: WFDMediaConfig, out_height: int,
                      bitrate: str, gop: int) -> list[str]:
    """The -c:v block every ffmpeg WFD sender uses, for whichever encoder exists."""
    if _ffmpeg_h264_encoder() == "libopenh264":
        return [
            "-c:v", "libopenh264",
            # libopenh264 rejects plain "baseline"; it only produces the
            # constrained subset, which is what WFD sinks get from x264 too.
            "-profile:v", ("constrained_baseline" if config.h264_profile == "baseline"
                           else config.h264_profile),
            "-level:v", _h264_level_for_mode(config),
            "-pix_fmt", "yuv420p",
            "-r", str(config.fps),
            # IDRs land only on the GOP boundary; libopenh264 exposes no
            # scene-cut switch and needs none. SPS/PPS precede every IDR, and
            # the mpegts muxer adds the access unit delimiters x264 writes.
            "-g", str(gop),
            "-b:v", bitrate,
            "-maxrate", bitrate,
            "-rc_mode", "bitrate",
            "-allow_skip_frames", "0",
        ]
    return [
        "-c:v", "libx264",
        "-preset", "ultrafast" if out_height > 1080 else "veryfast",
        "-tune", "zerolatency",
        "-threads", str(_x264_threads()),
        "-profile:v", config.h264_profile,
        "-level:v", _h264_level_for_mode(config),
        "-pix_fmt", "yuv420p",
        "-r", str(config.fps),
        "-g", str(gop),
        "-keyint_min", str(gop),
        "-sc_threshold", "0",
        "-bf", "0",
        "-b:v", bitrate,
        "-maxrate", bitrate,
        "-bufsize", _vbv_bufsize(bitrate, config),
        "-x264-params", "repeat-headers=1:aud=1",
    ]
