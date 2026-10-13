#!/usr/bin/env bash
# Build a FluxCast RPM from this checkout:
#   rpm/build_rpm.sh            ->  dist/fluxcast-<version>-<release>.noarch.rpm
#
# Packs the tracked files of the working tree (uncommitted edits included;
# new files only once `git add`ed), downloads the pinned wheels from
# rpm/vendor-requirements.txt, and runs rpmbuild in build/rpm.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$PWD
TOP=$ROOT/build/rpm

missing=()
for tool in rpmbuild desktop-file-validate git; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
python3 -m pip --version >/dev/null 2>&1 || missing+=("python3-pip")
if ((${#missing[@]})); then
    echo "Missing: ${missing[*]}"
    echo "Install the build tools with: sudo dnf install rpm-build desktop-file-utils python3-pip git"
    exit 1
fi

# v0.2.8-19-gda1460f -> Version 0.2.8, Release 19.<timestamp>.gda1460f. The
# timestamp makes every rebuild an upgrade, so `dnf install` picks it up.
describe=$(git describe --tags --long --always --abbrev=7)
if [[ $describe =~ ^v?([0-9][0-9.]*)-([0-9]+)-g([0-9a-f]+)$ ]]; then
    version=${BASH_REMATCH[1]}
    commits=${BASH_REMATCH[2]}
    sha=${BASH_REMATCH[3]}
else
    version=0.0.0
    commits=0
    sha=$(git rev-parse --short=7 HEAD)
fi
release="${commits}.$(date +%Y%m%d%H%M).g${sha}"

untracked=$(git ls-files --others --exclude-standard -- src meta rpm)
if [[ -n $untracked ]]; then
    echo "Warning: these files are not tracked by git and will NOT be packaged:"
    sed 's/^/  /' <<<"$untracked"
fi

rm -rf "$TOP"
mkdir -p "$TOP"/{SOURCES,SPECS,BUILD,RPMS,SRPMS} "$TOP/wheels" "$ROOT/dist"

git ls-files -z \
    | tar --null -T - --ignore-failed-read \
          --transform "s,^,fluxcast-${version}/," \
          -czf "$TOP/SOURCES/fluxcast-${version}.tar.gz"

python3 -m pip download --disable-pip-version-check --no-deps \
    --only-binary=:all: --platform any --implementation py --abi none \
    -r rpm/vendor-requirements.txt -d "$TOP/wheels"
tar -czf "$TOP/SOURCES/fluxcast-vendor-wheels.tar.gz" -C "$TOP/wheels" .

rpmbuild -bb \
    --define "_topdir $TOP" \
    --define "fc_version $version" \
    --define "fc_release $release" \
    rpm/fluxcast.spec

find "$TOP/RPMS" -name 'fluxcast-*.rpm' -exec cp -v {} "$ROOT/dist/" \;
echo
echo "Built. Install or upgrade with: rpm/install.sh"
