# Changelog

All notable changes to Legion Control are documented here. The project follows
[Semantic Versioning](https://semver.org/) while the public API and hardware
support surface mature.

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
