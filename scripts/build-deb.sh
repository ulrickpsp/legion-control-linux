#!/bin/sh
set -eu
umask 022
export LC_ALL=C

# 2026-08-11 00:00:00 UTC. Callers may override this standard build variable.
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-1786406400}
export SOURCE_DATE_EPOCH

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUTPUT_DIR=${1:-"$PROJECT_DIR/../outputs"}
BUILD_ROOT="$PROJECT_DIR/build"
PACKAGE_NAME="legion-control_0.8.0_all.deb"

mkdir -p "$BUILD_ROOT" "$OUTPUT_DIR"
STAGING_DIR=$(mktemp -d "$BUILD_ROOT/staging.XXXXXX")
chmod 0755 "$STAGING_DIR"
cleanup() {
    rm -rf -- "$STAGING_DIR"
}
trap cleanup EXIT HUP INT TERM

install -d \
    "$STAGING_DIR/DEBIAN" \
    "$STAGING_DIR/usr/bin" \
    "$STAGING_DIR/usr/lib/legion-control/legion_control" \
    "$STAGING_DIR/usr/libexec" \
    "$STAGING_DIR/usr/lib/systemd/system" \
    "$STAGING_DIR/usr/share/applications" \
    "$STAGING_DIR/usr/share/metainfo" \
    "$STAGING_DIR/usr/share/man/man1" \
    "$STAGING_DIR/usr/share/icons/hicolor/scalable/apps" \
    "$STAGING_DIR/usr/share/polkit-1/actions" \
    "$STAGING_DIR/usr/share/doc/legion-control"

for source in "$PROJECT_DIR"/legion_control/*.py; do
    install -m 0644 "$source" \
        "$STAGING_DIR/usr/lib/legion-control/legion_control/$(basename "$source")"
done

install -m 0755 "$PROJECT_DIR/packaging/bin/legion-control" \
    "$STAGING_DIR/usr/bin/legion-control"
install -m 0755 "$PROJECT_DIR/packaging/libexec/legion-control-helper" \
    "$STAGING_DIR/usr/libexec/legion-control-helper"
install -m 0755 "$PROJECT_DIR/packaging/libexec/legion-control-fand" \
    "$STAGING_DIR/usr/libexec/legion-control-fand"
install -m 0755 "$PROJECT_DIR/packaging/libexec/legion-control-rgbd" \
    "$STAGING_DIR/usr/libexec/legion-control-rgbd"
install -m 0644 "$PROJECT_DIR/packaging/systemd/legion-control-fand.service" \
    "$STAGING_DIR/usr/lib/systemd/system/legion-control-fand.service"
install -m 0644 "$PROJECT_DIR/packaging/systemd/legion-control-rgbd.service" \
    "$STAGING_DIR/usr/lib/systemd/system/legion-control-rgbd.service"
install -m 0644 "$PROJECT_DIR/packaging/polkit/io.github.ulrickpsp.policy" \
    "$STAGING_DIR/usr/share/polkit-1/actions/io.github.ulrickpsp.policy"
install -m 0644 \
    "$PROJECT_DIR/packaging/applications/io.github.ulrickpsp.LegionControl.desktop" \
    "$STAGING_DIR/usr/share/applications/io.github.ulrickpsp.LegionControl.desktop"
install -m 0644 \
    "$PROJECT_DIR/packaging/metainfo/io.github.ulrickpsp.LegionControl.metainfo.xml" \
    "$STAGING_DIR/usr/share/metainfo/io.github.ulrickpsp.LegionControl.metainfo.xml"
install -m 0644 \
    "$PROJECT_DIR/packaging/icons/io.github.ulrickpsp.LegionControl.svg" \
    "$STAGING_DIR/usr/share/icons/hicolor/scalable/apps/io.github.ulrickpsp.LegionControl.svg"
install -m 0644 "$PROJECT_DIR/README.md" \
    "$STAGING_DIR/usr/share/doc/legion-control/README.md"
install -m 0644 "$PROJECT_DIR/CHANGELOG.md" \
    "$STAGING_DIR/usr/share/doc/legion-control/CHANGELOG.md"
install -m 0644 "$PROJECT_DIR/SECURITY.md" \
    "$STAGING_DIR/usr/share/doc/legion-control/SECURITY.md"
install -m 0644 "$PROJECT_DIR/SUPPORT.md" \
    "$STAGING_DIR/usr/share/doc/legion-control/SUPPORT.md"
install -m 0644 "$PROJECT_DIR/THIRD_PARTY_NOTICES.md" \
    "$STAGING_DIR/usr/share/doc/legion-control/THIRD_PARTY_NOTICES.md"
for document in SAFETY HARDWARE-SUPPORT RGB-PROTOCOL RELIABILITY TROUBLESHOOTING; do
    install -m 0644 "$PROJECT_DIR/docs/$document.md" \
        "$STAGING_DIR/usr/share/doc/legion-control/$document.md"
done
install -m 0644 "$PROJECT_DIR/packaging/debian/copyright" \
    "$STAGING_DIR/usr/share/doc/legion-control/copyright"
gzip -n -9 -c "$PROJECT_DIR/packaging/man/legion-control.1" \
    > "$STAGING_DIR/usr/share/man/man1/legion-control.1.gz"

for source in "$PROJECT_DIR"/packaging/debian/*; do
    name=$(basename "$source")
    case "$name" in
        copyright) continue ;;
        postinst|prerm|postrm) mode=0755 ;;
        *) mode=0644 ;;
    esac
    install -m "$mode" "$source" "$STAGING_DIR/DEBIAN/$name"
done

installed_size=$(du -sk "$STAGING_DIR/usr" | awk '{print $1}')
printf 'Installed-Size: %s\n' "$installed_size" \
    >>"$STAGING_DIR/DEBIAN/control"

(
    cd "$STAGING_DIR"
    find usr -type f -exec md5sum '{}' \; | sort -k 2 \
        >DEBIAN/md5sums
)
chmod 0644 "$STAGING_DIR/DEBIAN/md5sums"

# Normalize every archive member. dpkg-deb also consumes SOURCE_DATE_EPOCH for
# the outer archive timestamp.
find "$STAGING_DIR" -exec touch -h -d "@$SOURCE_DATE_EPOCH" '{}' +

dpkg-deb --root-owner-group --build "$STAGING_DIR" "$OUTPUT_DIR/$PACKAGE_NAME"
printf '%s\n' "$OUTPUT_DIR/$PACKAGE_NAME"
