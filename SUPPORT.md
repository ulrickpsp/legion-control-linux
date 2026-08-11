# Support

Legion Control is a small community project, not a commercial support service.
Help is provided on a best-effort basis, with no guaranteed response time,
resolution, compatibility, or continued maintenance.

## Supported target

The mutation allowlist contains exactly one Lenovo product:

- DMI product name: `83LU`
- marketed model: Lenovo Legion Pro 5 16IAX10H
- physically tested environment: Ubuntu 26.04, Linux 7.0, BIOS `Q6CN79WW`
- tested RGB controller: ITE USB `048d:c195`, interface `00`, vendor feature
  report ID `0x07`

This is evidence from one hardware configuration, not a promise that every
regional SKU, keyboard option, BIOS revision, kernel, or distribution with a
similar name will work. See [`docs/HARDWARE-SUPPORT.md`](docs/HARDWARE-SUPPORT.md)
for the full boundary.

Other Lenovo Legion products, including machines also marketed as "Legion Pro
5," are unsupported unless their exact product code is separately validated
and added through a reviewed contribution. Do not bypass the allowlist.

## Before opening an issue

1. Read [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).
2. Return fan control to firmware before collecting diagnostics if cooling
   behavior is uncertain.
3. Reproduce with the latest published package or current source.
4. Check existing issues for the same product code and symptom.
5. Remove device serial numbers and personal information from all output.

For an ordinary bug, include:

- Legion Control version;
- exact DMI product name and product version;
- Ubuntu and kernel versions;
- BIOS version;
- what you expected, what happened, and whether it is reproducible;
- sanitized application or service logs;
- whether fan targets were restored to `0` afterward.

Use a separate issue for each reproducible problem. Paste text rather than
screenshots of logs when possible.

## Hardware requests

A USB ID, marketing name, or claim that another tool works is not enough to
enable writes. A new model requires read-only capability evidence, exact kernel
interfaces, reversible tests, failure-path tests, and a verified final safe
state. The process is described in
[`CONTRIBUTING.md`](CONTRIBUTING.md#hardware-support-contributions).

Maintainers may help interpret evidence, but they cannot promise remote support
for unowned hardware or ask a contributor to perform an unsafe experiment.

## Security and safety

- Do not publish suspected vulnerabilities. Follow [`SECURITY.md`](SECURITY.md).
- If the fans behave unexpectedly, stop manual control first. Follow
  [`docs/SAFETY.md`](docs/SAFETY.md#emergency-recovery).
- Do not run the GTK application as root, install a permissive `hidraw` rule,
  or add an unsupported product to the allowlist as a troubleshooting step.

This project is independent and is not affiliated with, endorsed by, or
supported by Lenovo. Lenovo product names and trademarks belong to their
respective owners.
