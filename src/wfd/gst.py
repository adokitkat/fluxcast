import re
import shutil
import subprocess
from typing import Optional

from diagnostics import (
    OPENH264_REQUIRES, PORTAL_GST_AAC_ENCODERS, PORTAL_GST_H264_ENCODERS,
)

from .config import WFDNotReady


def _gst_has_element(name: str) -> bool:
    if not shutil.which("gst-inspect-1.0"):
        return False
    try:
        result = subprocess.run(
            ["gst-inspect-1.0", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0

def _wfd_gst_prog_map(with_audio: bool, aosp_pmt_pid: bool = False) -> str:
    # PMT_<program> must be uint-typed; a plain int is parsed as gint and
    # silently ignored, leaving the PMT on mpegtsmux's 0x0020 default.
    prog_map = "program_map,sink_4113=1"
    if with_audio:
        prog_map += ",sink_4352=1"
    if aosp_pmt_pid:
        prog_map += ",PMT_1=(uint)256"
    return prog_map

def _gst_rtp_link(dump_ts_path: Optional[str]) -> list[str]:
    payloader = ["!", "rtpmp2tpay", "pt=33", "mtu=1328"]
    if not dump_ts_path:
        return payloader
    return ["!", "tee", "name=tsdump", "!", "queue"] + payloader

def _gst_dump_branch(dump_ts_path: Optional[str]) -> list[str]:
    if not dump_ts_path:
        return []
    return [
        "tsdump.",
        "!", "queue", "leaky=downstream", "max-size-buffers=512",
        "!", "filesink", f"location={dump_ts_path}", "async=false",
    ]

def _gst_wfd_sender_available() -> bool:
    return (
        shutil.which("gst-launch-1.0") is not None
        and _gst_has_element("mpegtsmux")
        and _gst_has_element("rtpmp2tpay")
        and _gst_pick_h264_encoder() is not None
    )

def _gst_vah264enc_rate_controls() -> set[str]:
    """Enum values vah264enc offers; rate-control modes depend on the VA driver."""
    try:
        result = subprocess.run(
            ["gst-inspect-1.0", "vah264enc"],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return set(re.findall(r"^\s+\(\d+\): ([a-z]+)\s+-", result.stdout, re.M))

def _gst_pipewiresrc_properties() -> set[str]:
    if not shutil.which("gst-inspect-1.0"):
        return set()
    try:
        result = subprocess.run(
            ["gst-inspect-1.0", "pipewiresrc"],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if result.returncode != 0:
        return set()

    props: set[str] = set()
    for line in result.stdout.splitlines():
        match = re.match(r"^\s{2}([a-z0-9_-]+)\s+:", line)
        if match:
            props.add(match.group(1))
    return props

# Cached at first call; x264enc version varies across distros.
_gst_x264enc_props_cache: Optional[set[str]] = None

def _gst_x264enc_properties() -> set[str]:
    """Return the set of property names supported by the installed x264enc.
    Cached after the first call.
    """
    global _gst_x264enc_props_cache
    if _gst_x264enc_props_cache is not None:
        return _gst_x264enc_props_cache
    if not shutil.which("gst-inspect-1.0"):
        _gst_x264enc_props_cache = set()
        return _gst_x264enc_props_cache
    try:
        result = subprocess.run(
            ["gst-inspect-1.0", "x264enc"],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        _gst_x264enc_props_cache = set()
        return _gst_x264enc_props_cache
    if result.returncode != 0:
        _gst_x264enc_props_cache = set()
        return _gst_x264enc_props_cache

    props: set[str] = set()
    for line in result.stdout.splitlines():
        match = re.match(r"^\s{2}([a-z0-9_-]+)\s+:", line)
        if match:
            props.add(match.group(1))
    _gst_x264enc_props_cache = props
    return props

def _pipewiresrc_selector_attempts(
    node_id: int,
    stream_label: str = "",
) -> list[tuple[str, list[str]]]:
    props = _gst_pipewiresrc_properties()
    attempts: list[tuple[str, list[str]]] = []
    has_autoconnect = "autoconnect" in props

    def _add(base_name: str, base_args: list[str]) -> None:
        # Try compositor-friendly selector mode first.
        if has_autoconnect:
            attempts.append((base_name, [*base_args, "autoconnect=true"]))
        else:
            attempts.append((base_name, base_args))
        # Then strict mode pinned to the selected node.
        if has_autoconnect:
            attempts.append((base_name + "+strict", [*base_args, "autoconnect=false"]))

    if "path" in props:
        _add("path", [f"path={node_id}"])
    # Keep target-object fallback disabled for now. On the tested KDE/PipeWire
    # stack this branch is unstable and can trigger gst-launch crashes. kurva...
    _ = stream_label
    if not attempts:
        raise WFDNotReady(
            "Portal backend could not target a specific PipeWire stream node: "
            "pipewiresrc has neither target-object nor path property."
        )
    return attempts


# Raw-audio caps each encoder accepts. The preference order lives in
# diagnostics.PORTAL_GST_AAC_ENCODERS so --doctor reports the same list (#129).
_AAC_ENCODER_CAPS = {
    "fdkaacenc": ["audio/x-raw,format=S16LE,rate=48000,channels=2,layout=interleaved"],
    "avenc_aac": ["audio/x-raw,rate=48000,channels=2"],
    "voaacenc": ["audio/x-raw,rate=48000,channels=2"],
    "faac": ["audio/x-raw,rate=48000,channels=2"],
}


def _gst_pick_aac_encoder() -> tuple[str, list[str]]:
    """
    Pick a broadly available AAC encoder and a compatible raw-audio caps filter.
    """
    for encoder in PORTAL_GST_AAC_ENCODERS:
        if _gst_has_element(encoder):
            return encoder, _AAC_ENCODER_CAPS[encoder]
    raise WFDNotReady(
        "No usable GStreamer AAC encoder found (tried "
        + ", ".join(PORTAL_GST_AAC_ENCODERS) + ")."
    )


def _gst_pick_h264_encoder() -> Optional[str]:
    """
    First usable element of diagnostics.PORTAL_GST_H264_ENCODERS, or None.

    x264enc stays first: it is what every pipeline was tuned against. The
    fallback is openh264enc, which is what stock Fedora has, since x264enc is
    only in RPM Fusion there. It needs h264parse after it, see
    _gst_openh264enc_args.
    """
    for encoder in PORTAL_GST_H264_ENCODERS:
        if encoder == "openh264enc" and not _gst_has_element(OPENH264_REQUIRES):
            continue
        if _gst_has_element(encoder):
            return encoder
    return None


def _gst_require_h264_encoder() -> str:
    encoder = _gst_pick_h264_encoder()
    if encoder is None:
        raise WFDNotReady(
            "No usable GStreamer H.264 encoder found: install x264enc "
            "(gst-plugins-ugly) or openh264enc with h264parse (gst-plugins-bad; "
            "Fedora: gstreamer1-plugin-openh264)."
        )
    if encoder != PORTAL_GST_H264_ENCODERS[0]:
        print(f"[FluxCast WFD Media] {PORTAL_GST_H264_ENCODERS[0]} not found; "
              f"encoding H.264 with {encoder}.")
    return encoder


def _gst_openh264enc_args(bitrate_kbits: int, gop: int) -> list[str]:
    """
    openh264enc settings matching what the x264enc pipelines ask of x264.

    Measured at 1080p60 / 12 Mb/s against x264enc veryfast:
    - usage-type=camera, not screen: as sharp on scrolling text (44.8 vs
      44.2 dB PSNR) and 1.5x faster. screen mode also overshot the target
      2.4x on flat content.
    - qp-min=10: without a floor openh264 spends far more than the target on
      easy frames. With it, the bitrate holds like x264's VBV cap.
    - scene-change-detection=false is x264's scenecut=0: IDRs only on the GOP
      boundary, so the sink sees the keyframe cadence it negotiated.
    - enable-frame-skip=false: dropped frames are what a sink shows as stutter.

    openh264enc writes SPS/PPS before every IDR but no access unit
    delimiters. Callers must follow it with h264parse, which adds them.
    """
    bps = bitrate_kbits * 1000
    return [
        "usage-type=camera",
        "rate-control=bitrate",
        f"bitrate={bps}",
        f"max-bitrate={bps}",
        "qp-min=10",
        "qp-max=51",
        f"gop-size={gop}",
        "scene-change-detection=false",
        "enable-frame-skip=false",
        "complexity=low",
        "multi-thread=0",
        "slice-mode=auto",
    ]


def _gst_h264_caps_profile(encoder: str, profile: str) -> str:
    """
    Profile for the video/x-h264 caps filter after `encoder`.

    openh264enc only produces Constrained Baseline, so asking it for "high"
    (a sink that advertises CHP) fails to negotiate. Every WFD sink has to
    decode Constrained Baseline, the mandatory WFD profile, so it stays on that.
    """
    return "baseline" if encoder == "openh264enc" else profile
