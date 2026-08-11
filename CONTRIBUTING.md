# Contributing to Legion Control

Thank you for helping improve Linux support for the validated Lenovo Legion
hardware. Correctness and reversibility take priority over feature count: this
application writes fan targets, power limits, platform profiles, device
features, and HID reports.

By submitting a contribution, you agree that your contribution is your
original work and may be distributed under this repository's MIT License. If
external research informed the work, identify it in the pull request and update
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) when needed. Do not copy or
translate incompatible-licensed source code.

## Development setup

Legion Control targets Python 3.12+, GTK4, and libadwaita. On Ubuntu:

```bash
sudo apt install \
  python3 python3-gi python3-cairo python3-gi-cairo \
  gir1.2-gtk-4.0 gir1.2-adw-1
```

Run the application against simulated telemetry while developing UI or domain
changes:

```bash
LEGION_CONTROL_MOCK=1 python3 -m legion_control.ui
```

Mock mode is the default development path. It avoids privileged and hardware
writes.

Lint and type checking are optional; the release gate skips them when they are
missing. Install them into your own prefix, without administrator rights:

```bash
./scripts/dev-tools.sh
```

That installs `ruff` and `pyright`, plus the PyGObject type stubs that pyright
needs to see GTK, libadwaita and GLib.

## Tests

Run the headless suite:

```bash
GSETTINGS_BACKEND=memory \
NO_AT_BRIDGE=1 \
XDG_CONFIG_HOME=/tmp/legion-control-test-config \
python3 -m unittest discover -v
```

Compile all Python modules:

```bash
python3 -m compileall -q legion_control tests
```

Lint, format and type-check:

```bash
ruff check legion_control tests && ruff format --check legion_control tests && pyright
```

`tests/test_a11y_names.py` starts the application and reads its accessibility
tree over AT-SPI, so it needs a graphical session; it skips elsewhere.

GTK widget tests require a real Wayland or X11 display. On a graphical Linux
session, run:

```bash
GSETTINGS_BACKEND=memory NO_AT_BRIDGE=1 \
python3 -m unittest -v tests.test_ui_state
```

Build the Debian package without installing it:

```bash
./scripts/build-deb.sh
```

Package installation, removal, PolicyKit, systemd, and physical hardware tests
are separate privileged gates. A passing unit suite is not evidence that a new
hardware path is safe.

## Design rules

- Keep thermal and validation rules independent from GTK and Linux adapters.
- Keep the unprivileged UI separate from the PolicyKit helper and root daemon.
- Privileged commands must use a closed grammar, fixed internal paths, bounded
  input, no shell, and no caller-controlled executable.
- Discover kernel interfaces by validated identity, not positional paths.
- Validate before every write and verify readback where the interface supports
  it.
- Every manual-fan failure path must attempt to restore firmware control.
- Do not add background networking, telemetry, runtime downloads, DKMS modules,
  BIOS writes, or firmware flashing.
- Keep lines readable within the configured 100-character limit and use Python
  type annotations for changed interfaces.
- Add a regression test before changing characterized behavior.

## Pull requests

Keep each pull request focused. Explain:

- the user-visible problem;
- the smallest change that solves it;
- safety and privilege-boundary effects;
- tests run and their results;
- real-hardware evidence, if any;
- rollback or recovery behavior;
- documentation and license-notice changes.

A pull request should not mix structural refactoring with behavior changes
unless separating them would make the change less safe. Avoid generated files,
build artifacts, bytecode caches, device serials, and private logs.

## Hardware-support contributions

Open an issue before implementing a new product, controller, kernel path, or
firmware behavior. Never test by deleting the current product check or by
writing arbitrary values to `sysfs`, ACPI/WMI, or `hidraw`.

New hardware support needs all of the following:

1. Exact DMI product name and product version, with serials removed.
2. Distribution, kernel, and BIOS versions.
3. Read-only discovery of the named kernel driver and its published limits.
4. For RGB, exact USB VID:PID, interface number, HID usage page, usage, report
   ID, report count, and report size.
5. A written test plan with bounded values and a recovery step before any
   privileged write.
6. Unit tests for wrong product, missing interface, malformed input, partial
   failure, concurrency, and restoration.
7. A reversible physical test on the exact device, starting and ending with
   firmware fan control active (`fan1_target=0`, `fan2_target=0`).
8. Updated hardware-support, safety, troubleshooting, and protocol docs.

Marketing names and shared USB IDs do not prove protocol compatibility. Each
exact product and controller combination remains unsupported until the evidence
is reviewed. Maintainers may decline a hardware contribution that cannot be
validated safely on accessible hardware.

## Documentation and user-facing text

Documentation should distinguish **tested**, **implemented**, **detected**, and
**expected**. Do not describe an inferred capability as supported. Commands
that change system state must state their effect and recovery path. Keep the
Lenovo non-affiliation disclaimer in public-facing support documents.

## Reporting problems

Use [`SUPPORT.md`](SUPPORT.md) for ordinary bugs and hardware requests. Follow
[`SECURITY.md`](SECURITY.md) for vulnerabilities. Participation is governed by
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
