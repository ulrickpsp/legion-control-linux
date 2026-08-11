#!/bin/sh
# Local, offline release gate. It never installs the generated package.
set -eu

umask 077
export LC_ALL=C

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CHECK_TMP_BASE=${TMPDIR:-/tmp}
CHECK_TMP=$(mktemp -d "$CHECK_TMP_BASE/legion-control-check.XXXXXX")

cleanup() {
    status=$?
    trap - 0 HUP INT TERM
    case "$CHECK_TMP" in
        "$CHECK_TMP_BASE"/legion-control-check.*)
            rm -rf -- "$CHECK_TMP"
            ;;
        *)
            printf '%s\n' "Refusing to remove unexpected temporary path: $CHECK_TMP" >&2
            ;;
    esac
    exit "$status"
}
trap cleanup 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

step() {
    printf '\n==> %s\n' "$1"
}

note() {
    printf '    %s\n' "$1"
}

fail() {
    printf '\nERROR: %s\n' "$1" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

require_command python3
require_command find
require_command grep
require_command dpkg-deb
require_command gzip
require_command cmp

step "Compiling Python sources"
PYTHONPYCACHEPREFIX="$CHECK_TMP/pycache" \
    python3 -m compileall -q "$PROJECT_DIR/legion_control" "$PROJECT_DIR/tests"

step "Linting and formatting Python sources"
if command -v ruff >/dev/null 2>&1; then
    (cd "$PROJECT_DIR" && ruff check legion_control tests)
    (cd "$PROJECT_DIR" && ruff format --check legion_control tests)
    note "ruff reported no findings"
else
    note "SKIP: ruff is not installed; run ./scripts/dev-tools.sh"
fi

step "Type-checking Python sources"
if command -v pyright >/dev/null 2>&1; then
    (cd "$PROJECT_DIR" && pyright)
    note "pyright reported no findings"
else
    note "SKIP: pyright is not installed; run ./scripts/dev-tools.sh"
fi

step "Running the headless unit test suite"
mkdir -p "$CHECK_TMP/config"
(
    cd "$PROJECT_DIR"
    PYTHONDONTWRITEBYTECODE=1 \
    GSETTINGS_BACKEND=memory \
    NO_AT_BRIDGE=1 \
    XDG_CONFIG_HOME="$CHECK_TMP/config" \
    XDG_STATE_HOME="$CHECK_TMP/state" \
        python3 -m unittest discover -v
)

step "Checking shell syntax"
find "$PROJECT_DIR/scripts" "$PROJECT_DIR/packaging" -type f -print \
    >"$CHECK_TMP/files-to-inspect.txt"
while IFS= read -r source_file; do
    first_line=
    IFS= read -r first_line <"$source_file" || :
    case "$first_line" in
        '#!'*'/bin/sh'*)
            sh -n "$source_file"
            ;;
        '#!'*'/usr/bin/env sh'*)
            sh -n "$source_file"
            ;;
        '#!'*'/bin/bash'*|'#!'*'/usr/bin/env bash'*)
            require_command bash
            bash -n "$source_file"
            ;;
    esac
done <"$CHECK_TMP/files-to-inspect.txt"

step "Validating desktop metadata"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate \
        "$PROJECT_DIR/packaging/applications/io.github.ulrickpsp.LegionControl.desktop"
else
    note "SKIP: desktop-file-validate is not installed"
fi

if command -v appstreamcli >/dev/null 2>&1; then
    APPSTREAM_LOG="$CHECK_TMP/appstream.log"
    if appstreamcli validate --no-net \
        "$PROJECT_DIR/packaging/metainfo/io.github.ulrickpsp.LegionControl.metainfo.xml" \
        >"$APPSTREAM_LOG" 2>&1; then
        note "AppStream metadata is valid"
    else
        diagnostic_count=$(grep -Ec '^[EWP]:' "$APPSTREAM_LOG" || :)
        if grep -Eq '^W: .*: url-homepage-missing$' "$APPSTREAM_LOG" \
            && [ "$diagnostic_count" -eq 1 ]; then
            note "KNOWN: AppStream homepage URL is pending; every other diagnostic is fatal"
        else
            cat "$APPSTREAM_LOG" >&2
            fail "AppStream validation failed"
        fi
    fi
else
    note "SKIP: appstreamcli is not installed"
fi

step "Building and inspecting the Debian package"
PACKAGE_OUTPUT="$CHECK_TMP/package"
BUILD_LOG="$CHECK_TMP/build.log"
CONTENTS_LOG="$CHECK_TMP/package-contents.txt"
mkdir -p "$PACKAGE_OUTPUT"
if ! sh "$PROJECT_DIR/scripts/build-deb.sh" "$PACKAGE_OUTPUT" >"$BUILD_LOG" 2>&1; then
    cat "$BUILD_LOG" >&2
    fail "Debian package build failed"
fi

set -- "$PACKAGE_OUTPUT"/legion-control_*_all.deb
[ "$#" -eq 1 ] || fail "Expected exactly one Debian package"
[ -f "$1" ] || fail "The Debian package was not created"
PACKAGE_FILE=$1

package_name=$(dpkg-deb --field "$PACKAGE_FILE" Package)
package_version=$(dpkg-deb --field "$PACKAGE_FILE" Version)
package_architecture=$(dpkg-deb --field "$PACKAGE_FILE" Architecture)
package_installed_size=$(dpkg-deb --field "$PACKAGE_FILE" Installed-Size)
[ "$package_name" = "legion-control" ] || fail "Unexpected package name: $package_name"
[ -n "$package_version" ] || fail "Package version is empty"
[ "$package_architecture" = "all" ] \
    || fail "Unexpected package architecture: $package_architecture"
[ -n "$package_installed_size" ] || fail "Installed-Size is missing"

dpkg-deb --info "$PACKAGE_FILE" >/dev/null
dpkg-deb --contents "$PACKAGE_FILE" >"$CONTENTS_LOG"
dpkg-deb --control "$PACKAGE_FILE" "$CHECK_TMP/control"
[ -s "$CHECK_TMP/control/md5sums" ] || fail "Package md5sums are missing"

if grep -Eq '(__pycache__/|\.py[co]$)' "$CONTENTS_LOG"; then
    grep -E '(__pycache__/|\.py[co]$)' "$CONTENTS_LOG" >&2
    fail "Python cache files leaked into the package"
fi

for required_path in \
    ./usr/bin/legion-control \
    ./usr/libexec/legion-control-helper \
    ./usr/libexec/legion-control-fand \
    ./usr/lib/systemd/system/legion-control-fand.service \
    ./usr/share/polkit-1/actions/io.github.ulrickpsp.policy \
    ./usr/share/applications/io.github.ulrickpsp.LegionControl.desktop \
    ./usr/share/metainfo/io.github.ulrickpsp.LegionControl.metainfo.xml \
    ./usr/share/man/man1/legion-control.1.gz \
    ./usr/share/doc/legion-control/THIRD_PARTY_NOTICES.md
do
    grep -F " $required_path" "$CONTENTS_LOG" >/dev/null \
        || fail "Required package path is missing: $required_path"
done

step "Confirming reproducible package output"
SECOND_PACKAGE_OUTPUT="$CHECK_TMP/package-second"
mkdir -p "$SECOND_PACKAGE_OUTPUT"
if ! sh "$PROJECT_DIR/scripts/build-deb.sh" "$SECOND_PACKAGE_OUTPUT" \
    >"$CHECK_TMP/build-second.log" 2>&1; then
    cat "$CHECK_TMP/build-second.log" >&2
    fail "Second Debian package build failed"
fi
SECOND_PACKAGE_FILE="$SECOND_PACKAGE_OUTPUT/$(basename "$PACKAGE_FILE")"
cmp -s "$PACKAGE_FILE" "$SECOND_PACKAGE_FILE" \
    || fail "Two clean package builds are not byte-for-byte identical"

note "Package verified: legion-control $package_version ($package_architecture)"
note "Installed-Size: $package_installed_size KiB; md5sums present"
note "Two clean builds are byte-for-byte identical"
note "No package was installed and no administrator privileges were used"

printf '\nPASS: local release gate completed successfully\n'
