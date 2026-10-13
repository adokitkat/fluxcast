#!/usr/bin/env bash
# Install or upgrade FluxCast from an RPM built by rpm/build_rpm.sh:
#   rpm/install.sh [path/to/fluxcast.rpm]     (default: newest in dist/)
#
# Before installing it offers to enable RPM Fusion and the codec packages
# FluxCast's best encoders need; an RPM cannot enable repositories itself.
# Remove FluxCast again with: sudo dnf remove fluxcast
set -euo pipefail
cd "$(dirname "$0")/.."

rpm_file=${1:-$(ls -t dist/fluxcast-*.noarch.rpm 2>/dev/null | head -n1 || true)}
if [[ -z $rpm_file || ! -f $rpm_file ]]; then
    echo "No FluxCast RPM found; build one first with rpm/build_rpm.sh"
    exit 1
fi
rpm_file=$(realpath "$rpm_file")

ask() {
    local reply
    read -r -p "$1 [y/N] " reply
    [[ $reply =~ ^[Yy] ]]
}
repo_enabled() { dnf repolist --enabled 2>/dev/null | grep -qE "^$1[[:space:]]"; }
installed() { rpm -q "$1" >/dev/null 2>&1; }

fedora=$(rpm -E %fedora)
if ! repo_enabled rpmfusion-free || ! repo_enabled rpmfusion-nonfree; then
    echo "RPM Fusion is not enabled. Without it FluxCast is missing:"
    echo "  - no x264enc, the default H.264 encoder for Miracast"
    echo "  - no H.264 in the GPU (VA-API) drivers, needed for --wfd-encoder va"
    if ask "Enable RPM Fusion (free and nonfree) now?"; then
        sudo dnf install \
            "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-${fedora}.noarch.rpm" \
            "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-${fedora}.noarch.rpm"
    fi
fi

if repo_enabled rpmfusion-free; then
    if installed ffmpeg-free && ask "Replace ffmpeg-free with RPM Fusion's ffmpeg (adds libx264 and libfdk_aac)?"; then
        sudo dnf swap ffmpeg-free ffmpeg --allowerasing
    fi

    # The GPU encoders only do H.264 with RPM Fusion's drivers.
    gpu_vendors=$(cat /sys/class/drm/card*/device/vendor 2>/dev/null | sort -u || true)
    if grep -q 0x8086 <<<"$gpu_vendors" && repo_enabled rpmfusion-nonfree && ! installed intel-media-driver; then
        if ask "Install intel-media-driver for H.264 encoding on the Intel GPU?"; then
            if installed libva-intel-media-driver; then
                sudo dnf swap libva-intel-media-driver intel-media-driver --allowerasing
            else
                sudo dnf install intel-media-driver
            fi
        fi
    fi
    if grep -q 0x1002 <<<"$gpu_vendors" && ! installed mesa-va-drivers-freeworld; then
        if ask "Switch to mesa-va-drivers-freeworld for H.264 encoding on the AMD GPU?"; then
            sudo dnf swap mesa-va-drivers mesa-va-drivers-freeworld --allowerasing
        fi
    fi
fi

sudo dnf install "$rpm_file"

# Older pip installs put a `fluxcast` earlier in PATH than /usr/bin.
for old in /usr/local/bin/fluxcast "$HOME/.local/bin/fluxcast"; do
    if [[ -e $old ]]; then
        echo
        echo "Warning: $old (an older pip install) runs instead of /usr/bin/fluxcast."
        if [[ $old == /usr/local/* ]]; then
            echo "  Remove it with: sudo pip uninstall fluxcast"
        else
            echo "  Remove it with: pip uninstall fluxcast"
        fi
    fi
done

echo
echo "FluxCast is installed. Start it from the application launcher, or run: fluxcast --tray"
echo "Remove it with: sudo dnf remove fluxcast"
