# Hardware Support

## Current support status

Legion Control currently permits hardware mutations on exactly one DMI product
code:

| Field | Validated value |
|---|---|
| DMI product name | `83LU` |
| marketed product | Lenovo Legion Pro 5 16IAX10H |
| tested operating system | Ubuntu 26.04 |
| tested kernel | Linux 7.0 |
| tested BIOS | `Q6CN79WW` |
| tested RGB USB ID | `048d:c195` |
| tested RGB interface | `00` |

The evidence comes from one physical laptop configuration. "Supported" here
means the code contains an explicit allowlist and the listed paths were tested
on that unit. It does not guarantee every regional SKU, keyboard option, BIOS
revision, Linux build, or future update with product code `83LU`.

## Validated capability paths

| Capability | Required identity or interface | Current scope |
|---|---|---|
| CPU/GPU temperature and fan telemetry | named Linux hwmon sensors and `lenovo_wmi_other` | read-only telemetry used by the UI and daemon |
| fan targets and bounds | `lenovo_wmi_other` with both target files and published min/max/step | automatic, fixed RPM, and validated curve modes |
| platform profiles | `lenovo-wmi-gamezone` platform-profile class device | choices discovered at runtime |
| Custom CPU power | Lenovo Other Mode WMI attributes `ppt_pl1_spl` and `ppt_pl2_sppt` with published bounds | sustained and slow limits in `custom` profile |
| device switches | present `VPC2004:00` attributes | conservation mode, Fn Lock, and camera power only when published |
| keyboard lighting | ITE `048d:c195`, interface `00`, vendor usage `0xFF89:0x07`, report ID `0x07` | 24 logical static zones, brightness, and off |

Capability discovery is intentionally conservative. A control is unavailable
when its exact kernel attribute or controller identity is missing, even on an
otherwise matching product.

## Not supported

The following are not supported unless future independent validation says
otherwise:

- any DMI product name other than `83LU`;
- another laptop sold under a similar "Legion Pro 5" marketing name;
- USB RGB controllers other than `048d:c195` on the validated interface and
  descriptor family;
- RGB interfaces `01` or HID LampArray as substitutes for interface `00`;
- animated RGB effects, per-key mappings beyond the documented 24 logical
  zones, or other chassis lighting;
- GPU/MUX switching, GPU overclocking, firmware flashing, BIOS changes, or
  third-party DKMS control modules;
- distributions, kernels, or BIOS revisions not listed above as physically
  tested.

Unsupported does not always mean impossible. It means the project has no safe,
reviewed evidence for writes. Do not work around the check by editing
`SUPPORTED_PRODUCTS`, forcing a `hidraw` path, or installing broad permissions.

## Check your identity safely

These commands are read-only:

```bash
printf 'product_name='; cat /sys/devices/virtual/dmi/id/product_name
printf 'product_version='; cat /sys/devices/virtual/dmi/id/product_version
printf 'bios_version='; cat /sys/devices/virtual/dmi/id/bios_version
printf 'kernel='; uname -r
. /etc/os-release
printf 'os=%s\n' "$PRETTY_NAME"
lsusb -d 048d:c195
```

Do not publish `product_serial`, `board_serial`, `chassis_serial`, a full
`dmidecode` dump, or unsanitized udev output. Those may identify a specific
machine.

To inspect only the discovered Lenovo fan directory:

```bash
for directory in /sys/class/hwmon/hwmon*; do
  if [ "$(cat "$directory/name" 2>/dev/null)" = "lenovo_wmi_other" ]; then
    printf '%s\n' "$directory"
    find "$directory" -maxdepth 1 -type f -printf '%f\n' | sort
  fi
done
```

These checks establish identity and presence only. They do not authorize a
write or prove behavior.

## Adding another model

A new exact product/controller combination requires a separate evidence set:
read-only discovery, kernel and descriptor identity, published bounds, a
bounded physical test, failure-path tests, and verified restoration to firmware
control. A marketing name or USB ID alone is insufficient.

Follow the hardware contribution process in
[`../CONTRIBUTING.md`](../CONTRIBUTING.md#hardware-support-contributions). The
maintainers make no promise that a requested model will be implemented.

This project is independent and is not affiliated with, endorsed by, or
supported by Lenovo.
