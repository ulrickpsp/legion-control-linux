# Changelog

All notable changes to Legion Control are documented here. The project follows
[Semantic Versioning](https://semver.org/) while the public API and hardware
support surface mature.

## 0.7.0 — 2026-08-12

### Added

- Six static RGB presets built from the verified transport: Hielo, Bosque,
  Neón, Brasa, Nocturno and Ajedrez.
- A restart button on the Language page, since the choice only applies on the
  next launch.
- The installed version in the Doctor report, on the page and in both terminal
  output formats.
- A button to restore the shipped fan curve.

### Changed

- Lighting applies on its own shortly after each change; the Apply button is
  gone. Writes are coalesced and serialized because each one crosses PolicyKit
  into the privileged helper.
- A preset no longer overwrites the chosen brightness.
- The thermal profile list no longer offers "custom"; it is a consequence of
  applying a curve or a fixed RPM and is now reported as state.
- Power limits are described by effect instead of by acronym, and the Apply
  button sits below the editor it confirms.
- Every preference group states whether it applies instantly or waits for
  Apply.
- Scene rows follow their automation switch.

### Fixed

- A failed lighting write no longer loses the colours on screen to the next
  status refresh.
- Preset buttons no longer fall below their minimum width; the row wraps.

## 0.6.0 — 2026-08-11

### Added

- Read-only Doctor page and terminal report (`legion-control doctor`) with
  copy/save support output.
- Seven-day local telemetry archive, 10 min/24 h/7 day views, change markers,
  and CSV export; samples are limited to one persisted record every 30 seconds.
- Opt-in, transition-only AC/battery scene automation while the UI stays open.
- Elevated/critical temperature notifications that never mutate hardware state.
- Optional StatusNotifier tray state and terminal status, scene, and
  restore-firmware workflows.
- Static 24-zone RGB wave and gradient presets using only the physically
  verified static ITE report sequence.
- English, Spanish, French, Simplified Chinese, and Russian interface
  localization with system-locale detection and a persistent in-app selector.
- Accessible names for every interactive control, checked against the live
  AT-SPI tree by the test suite.
- Optional `ruff` and `pyright` steps in the release gate, plus
  `scripts/dev-tools.sh` to install that tooling without administrator rights.

### Fixed

- CSV export and the Doctor report's save and copy actions, which failed
  silently inside their signal handlers on GTK4 APIs that do not exist there.
- Telemetry archive erasing itself once it passed its size budget, discarding
  up to seven days of history.
- View switcher truncating a tab label at 1366x768; the header now sheds its
  brand text and then moves navigation into a bottom switcher bar.
- Legend and graph contrast in the light colour scheme, which fell to 2.05:1.
- Doctor summary stretching the full row width, and short report values
  wrapping mid-token.
- A possibly-missing platform-profile path reaching the privileged writer.

### Changed

- Preference pages use a desktop content width instead of the 600px clamp
  libadwaita applies for phone-sized windows.

## 0.5.0 — 2026-08-11

### Added

- Public alpha status: one physically validated `83LU`, no inferred support
  for similar names or configurations, visible disclaimer and MIT terms.
- Public project identity for `ulrickpsp/legion-control-linux`.
- Offline release gate covering tests, compilation, desktop/AppStream metadata,
  shell syntax, Debian build, package contents, and cache exclusion.
- Direct tests for PolicyKit cancellation, process timeouts, malformed helper
  output, package safety, upgrade behavior, and daemon failure paths.
- Public safety, support, security, hardware, RGB protocol, troubleshooting,
  contribution, conduct, and third-party research documentation.
- Readback verification for both manual fan targets.
- VID/PID and HID report-descriptor validation from the opened RGB file
  descriptor.

### Changed

- Privileged operations now use a bounded cross-process lock; the GTK UI also
  rejects overlapping mutations.
- Failed Custom activation restores previous power limits as well as profile
  and firmware fan control.
- A restarted manual fan daemon reasserts and verifies the `custom` platform
  profile before writing targets.
- Deliberate safety exit status `3` no longer triggers a systemd restart loop.
- Failed RGB sequences invalidate stale saved readback.
- CSS moved into its own module, reducing the main GTK module without changing
  behavior.
- App ID changed to `io.github.ulrickpsp.LegionControl` before the first public
  release.

### Packaging

- Active manual service state is preserved for upgrades starting with this
  release; removal still restores firmware control and leaves the service off.
- The daemon receives a private `/dev` namespace in addition to the existing
  systemd hardening.

## 0.4.8 — 2026-08-11

### Fixed

- Replaced the ineffective LampArray path with the physically verified ITE
  Gen10 vendor transport for `048d:c195` interface `00`.
- Added 960-byte C8/CB/CE feature-report framing, 24 LED IDs, grouped static
  colors, and independent brightness.

## 0.4.1–0.4.7 — withdrawn internal builds

These unpublished builds explored incorrect HID LampArray/report assumptions.
They are retained in AppStream history for transparency but must not be used.

## 0.4.0 — 2026-07-28

### Added

- Custom fan/power coordination, 24-zone lighting UI, quick scenes, and local
  thermal history.

## 0.1.0 — 2026-07-27

- Initial model-specific GTK application for Lenovo product `83LU`.
