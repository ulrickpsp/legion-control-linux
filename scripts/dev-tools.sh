#!/bin/sh
# Install the optional lint and type-check tooling the release gate looks for.
# Everything lands in the user's own prefix; no administrator rights are used.
set -eu

fail() {
    printf '\nERROR: %s\n' "$1" >&2
    exit 1
}

note() {
    printf '    %s\n' "$1"
}

command -v uv >/dev/null 2>&1 \
    || fail "uv is required: see https://docs.astral.sh/uv/getting-started/installation/"
command -v python3 >/dev/null 2>&1 || fail "Required command not found: python3"

printf '\n==> Installing ruff and pyright\n'
uv tool install --force ruff
uv tool install --force pyright

printf '\n==> Installing PyGObject type stubs\n'
# The stubs must sit in the interpreter that provides `gi`, because that is the
# environment pyright analyses. `--no-deps` avoids rebuilding PyGObject and
# pycairo from source, which needs development headers and is not needed here:
# the package contains type information only.
USER_SITE=$(python3 -c 'import site; print(site.getusersitepackages())')
uv pip install --no-deps --target "$USER_SITE" pygobject-stubs

note "ruff:   $(uv tool dir)/ruff"
note "pyright: $(uv tool dir)/pyright"
note "stubs:  $USER_SITE/gi-stubs"

printf '\nPASS: run ./scripts/check.sh to use them\n'
