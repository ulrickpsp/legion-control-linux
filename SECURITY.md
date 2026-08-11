# Security Policy

Legion Control changes thermal, power, platform, and keyboard-lighting state on
one explicitly supported laptop. A bug at the privilege or hardware boundary
can have a greater impact than an ordinary desktop-application bug. Please
report such problems privately when a private channel is available.

## Supported versions

Only the latest published release is considered for security reports. Older
releases and development snapshots receive no security-support commitment.
Reports are handled on a best-effort basis; this community project offers no
response-time or remediation-time SLA.

Hardware support is separate from security support. The only mutation
allowlist is Lenovo product `83LU`, marketed as Legion Pro 5 16IAX10H. A report
that an unsupported model is refused is a support request, not a vulnerability.
A way to bypass that refusal can be a vulnerability.

## Reporting a vulnerability

1. Open the repository's **Security** tab and choose **Report a vulnerability**
   if GitHub Private Vulnerability Reporting is enabled.
2. Do not put exploit details, unsafe hardware-write instructions, firmware
   captures, or device serial numbers in a public issue.
3. If the private-reporting button is unavailable, this project does not yet
   have a dedicated confidential reporting channel. Open a public issue that
   asks the maintainers to enable private reporting, but include no sensitive
   technical details.
4. Ordinary hardening suggestions that do not expose an exploitable weakness
   may be filed publicly.

No project security email address or encryption key is currently published.
Please do not infer one from commit metadata or contributor profiles.

Include, when relevant:

- affected release or commit;
- impact and the privilege level needed to trigger it;
- minimal, safe reproduction steps;
- Lenovo product code, Ubuntu release, kernel version, and BIOS version;
- whether the issue affects the GTK process, PolicyKit helper, systemd daemon,
  package lifecycle, WMI/sysfs access, or HID transport;
- sanitized logs and the final fan-control state.

Remove serial numbers, usernames, home paths, tokens, and unrelated system logs
before sending a report. Do not stress the machine, lower cooling, flash
firmware, or bypass the model allowlist merely to produce a reproduction.

## Security scope

Examples of in-scope issues include:

- command, argument, environment, or path injection across the PolicyKit
  boundary;
- unauthorized use of the root helper;
- bypass of the exact product or RGB-controller checks;
- arbitrary filesystem or HID writes;
- unsafe parsing that reaches a privileged mutation;
- races that interleave fan, power, profile, service, or RGB operations;
- failure paths that prevent a reasonable attempt to restore firmware fan
  control;
- package maintainer scripts that remove unrelated state or leave manual fan
  control active.

Examples normally outside security scope include:

- requests to support another laptop, BIOS, distribution, or RGB controller;
- missing RGB effects or visual/UI defects;
- firmware behavior that the application neither causes nor can control;
- availability problems without a privilege, integrity, or hardware-safety
  impact.

## Disclosure process

Maintainers will assess whether the report is reproducible without unsafe
testing, determine affected versions, and coordinate a fix and advisory when
appropriate. Hardware availability may limit reproduction. Please allow time
for analysis before public disclosure, but note that the project makes no
embargo or response-time guarantee.

The thermal design and known limitations are documented in
[`docs/SAFETY.md`](docs/SAFETY.md). This software is independent and is not
affiliated with, endorsed by, or supported by Lenovo.
