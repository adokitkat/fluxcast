# Built by rpm/build_rpm.sh, which supplies the version, the source tarball
# and the vendored wheels; see that script for a local build.
%{!?fc_version: %global fc_version 0.0.0}
%{!?fc_release: %global fc_release 1}

# Everything lives in /opt/fluxcast; the vendored wheels are pure Python, so
# there is nothing to strip or debug, and nothing there should leak into the
# package's automatic Provides/Requires.
%global debug_package %{nil}
%global __provides_exclude_from ^/opt/fluxcast/.*$
%global __requires_exclude_from ^/opt/fluxcast/.*$

Name:           fluxcast
Version:        %{fc_version}
Release:        %{fc_release}%{?dist}
Summary:        Stream your Linux desktop to a Smart TV via Miracast/WFD, DLNA, or Cast
License:        GPL-3.0-or-later
URL:            https://github.com/IlyaP358/fluxcast
Source0:        %{name}-%{version}.tar.gz
Source1:        %{name}-vendor-wheels.tar.gz
BuildArch:      noarch

BuildRequires:  bash
BuildRequires:  python3
BuildRequires:  python3-pip
BuildRequires:  desktop-file-utils

Requires:       python3 >= 3.10
Requires:       python3-gobject
Requires:       python3-pillow
Requires:       python3-tkinter
Requires:       python3-dbus-next
Requires:       python3-zeroconf
Requires:       python3-requests
Requires:       python3-lxml
Requires:       python3-dateutil
Requires:       python3-ifaddr
Requires:       python3-six
Requires:       python3-xlib
Requires:       python3-casttube
Requires:       gtk3
Requires:       (libayatana-appindicator-gtk3 or libappindicator-gtk3)
Requires:       libnotify
Requires:       NetworkManager
Requires:       wpa_supplicant
Requires:       iw
Requires:       iproute
Requires:       xdg-desktop-portal
Requires:       pulseaudio-utils
Requires:       pipewire-gstreamer
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
# vah264enc (--wfd-encoder va) and fdkaacenc (FDK AAC, via fdk-aac-free)
Requires:       gstreamer1-plugins-bad-free
# Satisfied by RPM Fusion's ffmpeg or Fedora's ffmpeg-free alike.
Requires:       /usr/bin/ffmpeg

Recommends:     dnsmasq
Recommends:     avahi-tools
Recommends:     wf-recorder
Recommends:     xrandr
Recommends:     gstreamer1-plugin-libav
Recommends:     gstreamer1-plugin-openh264
# RPM Fusion: x264enc, the default WFD encoder. Weak, so the install still
# succeeds without RPM Fusion; rpm/install.sh offers to enable it.
Recommends:     gstreamer1-plugins-ugly

%description
FluxCast mirrors a Linux desktop to a Smart TV over Miracast/Wi-Fi Display
(Wi-Fi Direct or the LAN), DLNA, or Chromecast, with a system tray applet and
a command line interface.

%prep
%autosetup -n %{name}-%{version}
mkdir -p wheels
tar -xzf %{SOURCE1} -C wheels

%build
# Nothing to build: FluxCast runs from source.

%install
env DESTDIR=%{buildroot} FLUXCAST_VERSION="%{version}-%{release}" ./meta/install.sh

python3 -m pip install --no-deps --no-index --no-compile --disable-pip-version-check \
    --target %{buildroot}/opt/fluxcast/vendor wheels/*.whl
rm -rf %{buildroot}/opt/fluxcast/vendor/bin

# /opt is root-owned, so compile now rather than miss the cache on every start.
python3 -m compileall -q -j0 -d /opt/fluxcast %{buildroot}/opt/fluxcast

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{name}.desktop

%post
# Load the Wi-Fi Direct D-Bus policy now instead of at the next boot.
systemctl reload dbus.service >/dev/null 2>&1 || :

%postun
systemctl reload dbus.service >/dev/null 2>&1 || :

%files
%license LICENSE
%doc README.md documentation/DOCUMENTATION.md
/opt/fluxcast
%{_bindir}/%{name}
%{_datadir}/applications/%{name}.desktop
%{_datadir}/icons/hicolor/512x512/apps/%{name}.png
%{_datadir}/dbus-1/system.d/zz-dev.fluxcast.wpa-supplicant.conf
