# Troubleshooting

Start with safety. If fan behavior is unexpected, temperatures are rising, or
you are unsure who controls the fans, stop heavy workloads and follow
[`SAFETY.md#emergency-recovery`](SAFETY.md#emergency-recovery) before collecting
more diagnostics.

## Collect a small, safe diagnostic set

These commands are read-only:

```bash
printf 'product_name='; cat /sys/devices/virtual/dmi/id/product_name
printf 'product_version='; cat /sys/devices/virtual/dmi/id/product_version
printf 'bios_version='; cat /sys/devices/virtual/dmi/id/bios_version
printf 'kernel='; uname -r
. /etc/os-release
printf 'os=%s\n' "$PRETTY_NAME"
systemctl is-active legion-control-fand.service
systemctl is-enabled legion-control-fand.service
systemctl status legion-control-fand.service --no-pager
lsusb -d 048d:c195
```

Review output before posting it. Never include DMI serial files, a full
`dmidecode` dump, or unsanitized udev/environment output.

Service logs for the current boot:

```bash
journalctl -u legion-control-fand.service -b --no-pager -n 100
```

Some systems restrict journal access. If authorization is needed, collect only
this unit's bounded log and sanitize it before sharing.

## The application says the laptop is unsupported

The DMI product name must be exactly `83LU`. A similar retail name is not
enough:

```bash
cat /sys/devices/virtual/dmi/id/product_name
cat /sys/devices/virtual/dmi/id/product_version
```

Do not edit the allowlist. If the output is not `83LU`, the machine is outside
the current hardware boundary. See [`HARDWARE-SUPPORT.md`](HARDWARE-SUPPORT.md).

If it is `83LU`, include the sanitized versions, Ubuntu release, kernel, BIOS,
and missing capability in a support issue.

## No temperature, fan, profile, power, or device control appears

Controls are shown only when the expected kernel interface and its required
attributes exist. Check for the named Lenovo fan driver:

```bash
for directory in /sys/class/hwmon/hwmon*; do
  if [ "$(cat "$directory/name" 2>/dev/null)" = "lenovo_wmi_other" ]; then
    printf '%s\n' "$directory"
    find "$directory" -maxdepth 1 -type f -printf '%f\n' | sort
  fi
done
```

A matching product with missing attributes may indicate a kernel, BIOS, or SKU
difference. Do not substitute similarly named sysfs files or install a
third-party DKMS driver as a quick fix.

## Administrator authorization is cancelled or unavailable

The UI must run as the desktop user in an active graphical session. It calls a
fixed helper through PolicyKit when a mutation is applied.

- Do not start the GTK application with `sudo`.
- Confirm `pkexec`, PolicyKit, and the installed policy package are present.
- Make sure the desktop session can display its normal PolicyKit prompt.
- If you cancel the prompt, no change is applied; retry only when ready.
- If authorization times out, close stale prompts and try one operation again.

Repeated prompts for one click or a helper-path error should be reported with
sanitized application output and package version.

## A fan curve will not start

The helper rejects a curve when temperatures are not strictly increasing, RPM
falls as temperature rises, RPM is outside the detected bounds, or RPM does not
match the hardware step. Custom power also requires the `custom` platform
profile and firmware-published limits.

Check the service after applying:

```bash
systemctl status legion-control-fand.service --no-pager
journalctl -u legion-control-fand.service -b --no-pager -n 100
```

At or above 98 °C, or when neither CPU nor GPU temperature is trustworthy, the
daemon deliberately exits with status `3`, restores firmware control, and is
not restarted by systemd. This is a safety action, not a curve to force back on.

## Fan targets do not return to automatic

Use the recovery sequence:

```bash
sudo systemctl disable --now legion-control-fand.service
sudo /usr/libexec/legion-control-fand --restore-auto
```

Then verify both Lenovo targets are `0` using the read-only command in
[`SAFETY.md`](SAFETY.md#emergency-recovery). If they are not `0`, or cooling is
not responding, shut down rather than attempting guessed writes.

## RGB control is unavailable

The validated endpoint is all of the following at once:

- product `83LU`;
- USB `048d:c195`;
- interface `00`;
- vendor usage page `0xFF89`, usage `0x07`;
- report ID `0x07`, 960-byte userspace feature report.

Confirm only the public USB ID first:

```bash
lsusb -d 048d:c195
```

The same USB device may expose multiple HID interfaces. Interface `01`
LampArray is not a substitute. Do not force a `/dev/hidrawN` path or install a
world-readable/world-writable udev rule; hidraw numbers can change after boot or
hotplug.

## RGB apply succeeds but the keyboard does not change

An accepted HID ioctl is not semantic readback. Try these bounded steps:

1. Apply one obvious solid static color at a nonzero brightness.
2. Wait for the operation to finish before applying another.
3. If `Fn+Space` was pressed, reapply the configuration; the key can select a
   different firmware profile or effect.
4. Confirm the UI still detects 24-zone control after a reboot.
5. If the controller appears stalled, stop testing, reboot once, and collect
   only sanitized identity and application/service logs.

Do not probe unknown feature-report reads or replay packets from another model.
The current transport, limitations, and profile behavior are documented in
[`RGB-PROTOCOL.md`](RGB-PROTOCOL.md).

## Saved RGB state differs from visible lighting

`/var/lib/legion-control/rgb-config.json` records the last configuration whose
report sequence the helper accepted. A failed sequence removes this saved state
because partial controller state is unknowable. The controller has no
trustworthy full readback. Firmware profile changes, `Fn+Space`, reboot
behavior, or a later controller failure can still make visible lighting differ.
Reapply a known static preset rather than editing the root-owned JSON manually.

## Run without touching hardware

UI and workflow problems can be reproduced safely in mock mode:

```bash
LEGION_CONTROL_MOCK=1 python3 -m legion_control.ui
```

Mock mode does not validate real kernel, PolicyKit, systemd, fan, power, or HID
behavior.

## Package removal

Normal package removal stops the fan daemon and attempts to restore firmware
control:

```bash
sudo apt remove legion-control
```

`purge` additionally removes the two root-owned saved control configurations.
It is not a hardware-recovery substitute; use the explicit recovery sequence
first if fan state is uncertain.

## Ask for help

Follow [`../SUPPORT.md`](../SUPPORT.md). Include versions, exact product code,
sanitized logs, reproduction steps, and final fan-target state. Do not publish
serials, unsafe raw HID instructions, or suspected vulnerability details.

This project is independent and is not affiliated with, endorsed by, or
supported by Lenovo.
