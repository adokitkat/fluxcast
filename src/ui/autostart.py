"""Start-at-login entry and single-instance lock for the tray."""

from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path
from typing import IO

# An installed copy runs from here and is started through this wrapper
# (meta/install.sh, the RPM and the .deb all use this layout).
_INSTALL_DIR = Path("/opt/fluxcast")
_INSTALLED_LAUNCHER = "/usr/bin/fluxcast"
_MAIN = Path(__file__).resolve().parent.parent / "main.py"


def _config_home() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    return Path(config_home).expanduser() if config_home else Path.home() / ".config"


def autostart_path() -> Path:
    return _config_home() / "autostart" / "fluxcast.desktop"


def _quote(arg: str) -> str:
    """Quote one Exec argument per the Desktop Entry spec."""
    arg = arg.replace("%", "%%")
    if not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    for c in ('\\', '"', '`', '$'):
        arg = arg.replace(c, "\\" + c)
    return f'"{arg}"'


def launch_command() -> list[str]:
    """How to start this copy of FluxCast again: AppImage, installed or checkout."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return [appimage]
    if _MAIN.parent == _INSTALL_DIR and os.access(_INSTALLED_LAUNCHER, os.X_OK):
        return [_INSTALLED_LAUNCHER]
    return [sys.executable, str(_MAIN)]


def desktop_entry(command: list[str]) -> str:
    # TryExec makes the session skip the entry once FluxCast is uninstalled,
    # since package removal cannot reach this per-user file.
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=FluxCast\n"
        "Comment=Stream your desktop to a Smart TV\n"
        f"Exec={' '.join(_quote(a) for a in [*command, '--tray'])}\n"
        f"TryExec={command[0]}\n"
        "Icon=fluxcast\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def is_enabled() -> bool:
    return autostart_path().is_file()


def set_enabled(enabled: bool) -> None:
    path = autostart_path()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desktop_entry(launch_command()), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def _lock_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path("/tmp")
    return base / f"fluxcast-tray-{os.getuid()}.lock"


def acquire_tray_lock(path: Path | None = None) -> IO | None:
    """Hold an exclusive lock for this session's tray; None if one already runs.

    The lock lives as long as the returned file stays open, and the kernel
    drops it when the process exits, so a crashed tray never blocks a restart.
    """
    lock_file = open(path or _lock_path(), "a")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    return lock_file
