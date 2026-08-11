# Hardware Safety

Legion Control is a userspace control tool, not a replacement for laptop
firmware, thermal protection, or responsible monitoring. It has been physically
tested on one Lenovo Legion Pro 5 16IAX10H (`83LU`) configuration. Using it can
still expose firmware, kernel, driver, or application defects.

If cooling becomes uncertain, stop heavy workloads and return fan control to
firmware immediately. Do not keep testing to obtain better logs.

## Safety boundary

Mutating operations require all applicable checks:

- DMI product name exactly `83LU`;
- expected Lenovo WMI/sysfs interfaces discovered by driver identity;
- hardware-published bounds and steps for fan and power values;
- for RGB, USB `048d:c195`, interface `00`, vendor usage page `0xFF89`, usage
  `0x07`, and report ID `0x07`;
- administrator authorization through the installed PolicyKit action.

The GTK application remains unprivileged. It invokes a fixed root-owned helper
with a closed command grammar. The helper accepts no filesystem path or shell
fragment from the UI. The package does not install a permissive HID udev rule,
a third-party kernel module, or a firmware component.

Do not bypass any identity check. A shared marketing name, USB ID, or similar
sysfs layout does not prove compatible write semantics.

## Thermal policy

Manual fixed-RPM and curve modes run in a root systemd service with a two-second
control interval. The policy uses the hotter available CPU/GPU temperature.

| Condition | Behavior |
|---|---|
| Normal curve operation | Validate, interpolate, quantize, and apply equal targets to both fans. |
| At or above 92 °C | Bypass normal filtering and request the hardware-published maximum RPM. |
| At or above 98 °C | Do not write another manual target; exit with status `3` and restore firmware control. |
| No trustworthy CPU or GPU temperature | Exit with status `3` and restore firmware control. |
| Target write failure or daemon exception | Attempt firmware restoration in the daemon's `finally` path. |
| Service stop | Run a second restoration through systemd `ExecStopPost`. |

Firmware control is restored by writing `0` to both Lenovo fan-target
attributes. The service unit does not restart after the deliberate thermal exit
status `3`. Other unexpected failures may be restarted by systemd; each daemon
attempt still executes its restoration path.

When one fan-target write fails, the adapter attempts to restore both targets.
Package removal disables and stops the service and then attempts a direct
firmware restoration before files are removed. Installing the package does not
enable manual fan control.

## Power and platform profiles

Custom power writes are permitted only in the `custom` platform profile and
only within the minimum, maximum, and step values published by the Lenovo
kernel interface. Values are read back after writes. The helper snapshots the
previous profile and power values and attempts rollback if combined Custom
activation fails.

Rollback is best effort. Kernel, firmware, device, power-loss, or process
failure can prevent recovery code from completing. Always verify the displayed
profile and power state after an error.

## Scene automation and alerts

AC/battery automation is off by default, is configured in the unprivileged
user session, and runs only while the application remains open. It reacts only
to a detected source transition, never on initial startup. Each selected scene
still uses the existing bounded PolicyKit helper, hardware allowlist, and
readback rules; do not enable it until its saved scene is appropriate for both
contexts.

Temperature alerts are read-only notifications. They do not alter fan, power,
profile, or RGB state. At elevated or critical temperature, reduce workload and
use the explicit firmware-restore action if cooling ownership is uncertain.

## RGB safety

RGB output is limited to one exact controller path and fixed-size feature
reports. The helper serializes privileged operations, validates a versioned
24-zone document, keeps one HID file descriptor open for the sequence, uses a
10 ms inter-report delay, and persists public state only after all ioctls report
success.

Important limitations:

- Applying lighting writes controller profile `1` and may replace the lighting
  previously stored in that profile.
- `Fn+Space` can select another firmware lighting profile or effect after the
  application writes its configuration.
- The controller provides no trustworthy semantic readback for the complete
  static configuration. An accepted ioctl proves transport success, not that
  every LED visibly changed.
- Static colors, off, gradients, waves, and locally rendered animations are
  implemented. Firmware animation commands are intentionally outside scope.
- A disconnect or controller stall remains possible, but a replaced hidraw node
  is rejected by revalidating VID/PID and descriptor from the opened FD.

See [`RGB-PROTOCOL.md`](RGB-PROTOCOL.md) for the exact observed framing.

Gradient and wave presets are static 24-zone frames encoded with that same
verified profile `1` sequence. They do not use animation/effect commands and
must not be represented as firmware animation support.

## Animated effects

Animated effects are drawn by this project, one static frame at a time. The
keyboard is never told to animate itself; no effect, speed, or direction
command is sent, and the opaque constant bytes in each colour group are
reproduced unchanged.

Frames come from a root service, `legion-control-rgbd`, because authorizing
each frame through PolicyKit would spawn a privileged process 20 times a
second. That service is a smaller target than the fan daemon:

| Property | Behavior |
|---|---|
| Devices | `DevicePolicy=closed` with a single `char-hidraw rw` allowance. `PrivateDevices` cannot be used because the controller is a `/dev/hidrawN` node. |
| Filesystem | `ProtectSystem=strict` and `ProtectHome=yes`; it reads its settings and writes nothing. |
| Capabilities | Empty bounding and ambient sets, `NoNewPrivileges=yes`. |
| Network | `PrivateNetwork=yes`, `RestrictAddressFamilies=AF_UNIX AF_NETLINK`. |
| Identity | The same VID/PID and report-descriptor checks as a static write, run on the descriptor the frames are written to. |
| Failure | One reopen covers a resume-time re-enumeration; a second failure exits instead of retrying, and `StartLimitBurst=3` stops systemd from restarting it forever. |
| Stop | The service restores the last saved static configuration, in its own `finally` path and again through `ExecStopPost`. |

The animation never starts on its own. It runs only after an effect is chosen,
and any static change — a preset, a zone colour, turning lighting off — stops
it first, because two writers on one controller would fight over the keyboard.

Whether the colour command reaches non-volatile controller storage is not
established by this project's evidence. See the controller-wear section in
[`RGB-PROTOCOL.md`](RGB-PROTOCOL.md) for how that is assessed and what remains
unknown.

## Known limits of the safety model

- Userspace recovery cannot run during a kernel hang, abrupt power loss, or
  complete system lockup.
- The current release checks accepted target writes but does not yet implement
  a sustained fan-response/stall watchdog.
- Suspend/resume with a manual curve and sustained combined CPU/GPU load are
  not yet part of the published physical-validation evidence.
- Only one `83LU` unit, running Ubuntu 26.04, Linux 7.0, and BIOS `Q6CN79WW`,
  has been physically validated.
- A future BIOS or kernel may change an otherwise matching interface.

These limitations are reasons to monitor initial use, not invitations to weaken
the checks.

## Emergency recovery

Prefer the application's **Auto / return to firmware** action. If the UI is not
available, use the installed service and helper:

```bash
sudo systemctl disable --now legion-control-fand.service
sudo /usr/libexec/legion-control-fand --restore-auto
```

Both commands change system state. The first prevents the manual service from
starting automatically and triggers its stop restoration. The second directly
writes `0` to both supported fan targets.

Verify the Lenovo target files without writing to them:

```bash
for directory in /sys/class/hwmon/hwmon*; do
  if [ "$(cat "$directory/name" 2>/dev/null)" = "lenovo_wmi_other" ]; then
    printf '%s\n' "fan1_target=$(cat "$directory/fan1_target" 2>/dev/null)"
    printf '%s\n' "fan2_target=$(cat "$directory/fan2_target" 2>/dev/null)"
  fi
done
```

The expected firmware-controlled value is `0` for both targets. If restoration
fails, targets remain nonzero, a fan stops responding, or temperatures continue
to rise:

1. stop CPU/GPU-intensive work;
2. save unrelated work if it is safe to do so;
3. shut the laptop down rather than continuing diagnostics;
4. use firmware/OEM recovery and hardware service as appropriate.

Do not compensate by writing guessed RPM, WMI, ACPI, or HID values.

## Responsible physical testing

Before a hardware test, write down the starting profile, power limits, fan
targets, observed fan RPM, and recovery command. Use bounded changes, observe
both fans and temperatures, test one behavior at a time, and finish with both
targets at `0`. Never leave an unattended manual curve active during initial
validation.

This project is independent and is not affiliated with, endorsed by, or
supported by Lenovo.
