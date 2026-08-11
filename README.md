# Legion Control

Native GTK4/libadwaita control center for the Lenovo Legion Pro 5 16IAX10H
(`83LU`) on Linux.

> [!WARNING]
> **Status: alpha.** The physical validation behind this project was performed
> on one unit, with 0.5.0. Version 0.6.0 has not been re-validated against
> hardware; it was verified with the offline gate and simulated telemetry only.
> This is not a compatibility promise for another laptop, although truly
> equivalent units —same `83LU` DMI, BIOS, ITE controller, and WMI attributes—
> are more likely to behave the same. The application does not expand its
> allowlist from a marketing name or apparent similarity.

> [!IMPORTANT]
> Hardware writes are allowlisted for product `83LU` only. Similar Legion
> names do not imply compatibility. Do not bypass the model check.

Legion Control exists because broad Legion toolkits do not currently provide
the verified Gen10 path this laptop needs: in-kernel Lenovo WMI for thermal and
power controls, plus the 24-zone ITE `048d:c195` keyboard protocol. It uses no
DKMS module, firmware flash, account, telemetry, or network service.

## Features

- CPU/GPU temperature, both fan speeds, battery state, plus local history views
  for ten minutes, 24 hours, and seven days with CSV export and change markers.
- Lenovo platform profiles.
- Firmware automatic, fixed-RPM, and validated temperature-curve fan modes.
- Custom sustained/slow CPU power limits within firmware-published bounds.
- Static 24-zone RGB, brightness, presets, wave/gradient frames, and off for
  ITE `048d:c195`.
- Three local quick scenes: Silence, Work, and Game.
- Opt-in AC/battery scene automation while the application is open.
- Battery conservation, Fn Lock, and camera power when exposed by the kernel.
- Native PolicyKit authorization and a hardened systemd fan daemon.
- Read-only Doctor report, copy/save support bundle, StatusNotifier tray state,
  and terminal workflows.
- Interface localization for English, Spanish, French, Simplified Chinese, and
  Russian. It follows the system locale or the saved in-app language choice.

## Verified hardware

| Field | Verified value |
|---|---|
| Product | Lenovo Legion Pro 5 16IAX10H |
| DMI product name | `83LU` |
| Ubuntu | 26.04 |
| Kernel | Linux 7.0 |
| BIOS | `Q6CN79WW` |
| Keyboard | ITE USB `048d:c195` |
| RGB endpoint | interface `00`, usage `0xFF89:0x07`, report ID `0x07` |

This evidence comes from one physical unit. Other BIOS versions, regional
SKUs, distributions, kernels, and controllers are not claimed as supported.
Ubuntu 22.04 is not supported because its default Python is older than the
required Python 3.12. See
[`docs/HARDWARE-SUPPORT.md`](docs/HARDWARE-SUPPORT.md).

Before any write on another unit, compare its identity with the table above,
run only the hardware guide's read-only checks, and keep firmware fan control
available. A matching marketing name alone is not enough.

## Safety model

- The GTK application remains unprivileged.
- PolicyKit invokes one fixed root-owned helper with a closed command grammar.
- Privileged changes are serialized across processes.
- Fan and power values are validated against detected hardware bounds and
  verified through readback.
- At 92 °C the daemon requests maximum RPM. At 98 °C, or without a trustworthy
  temperature, it restores firmware control and exits without a restart loop.
- Stop, package removal, and failure paths attempt to write `0` to both fan
  targets, returning control to firmware.
- The RGB writer revalidates VID/PID and the Gen10 descriptor from the opened
  HID file descriptor before sending bounded 960-byte feature reports.
- No broad `hidraw` udev permission is installed.
- Thermal notifications only inform; they never issue an unrequested hardware
  write. The restore-to-firmware action remains explicit.

Read [`docs/SAFETY.md`](docs/SAFETY.md) before using manual fan or power
control. This is independent community software, not affiliated with or
endorsed by Lenovo.

## Install a release

Download the `.deb` from the repository's Releases page, then install it with
APT so dependencies and package lifecycle scripts are applied:

```bash
sha256sum --check SHA256SUMS
sudo apt install ./legion-control_0.6.0_all.deb
```

Launch **Legion Control** from the application grid.

Removal stops the daemon and attempts firmware restoration:

```bash
sudo apt remove legion-control
```

Use `sudo apt purge legion-control` only when you also want to remove saved fan
and RGB configuration.

## Build from source

Install development dependencies on Ubuntu:

```bash
sudo apt install \
  python3 python3-gi python3-cairo python3-gi-cairo \
  gir1.2-gtk-4.0 gir1.2-adw-1 desktop-file-utils appstream
```

Run the UI safely with simulated hardware:

```bash
LEGION_CONTROL_MOCK=1 python3 -m legion_control.ui
```

Open the **Language** page to select English, Spanish, French, Simplified
Chinese, or Russian. The preference is stored under the user configuration
directory and applies the next time Legion Control opens. To test a locale for
one launch without saving it, set `LEGION_CONTROL_LANGUAGE` to `en`, `es`,
`fr`, `zh`, or `ru`.

Read-only terminal workflows:

```bash
legion-control status
legion-control doctor
legion-control doctor --json
```

Applying a scene or restoring firmware through the terminal uses the same
PolicyKit helper and allowlist as the UI:

```bash
legion-control scene work
legion-control restore-firmware
```

The optional tray indicator uses the desktop StatusNotifier protocol. When a
watcher is present, closing the window keeps the indicator available; activate
it to reopen Legion Control. Without a watcher, closing the window exits
normally.

Use `Ctrl+1` through `Ctrl+6` to jump to Inicio, Ventilación, Iluminación,
Dispositivo, Automatización, and Doctor.

Run the complete offline, unprivileged release gate:

```bash
./scripts/check.sh
```

Build a Debian package without installing it:

```bash
./scripts/build-deb.sh
```

Physical hardware testing and package installation are separate privileged
gates. A successful unit suite is not evidence for a new laptop model.

## Project documentation

- [Hardware support](docs/HARDWARE-SUPPORT.md)
- [Safety and emergency recovery](docs/SAFETY.md)
- [RGB protocol notes](docs/RGB-PROTOCOL.md)
- [Reliability and rollback](docs/RELIABILITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Support](SUPPORT.md)
- [Security policy](SECURITY.md)
- [Third-party research acknowledgements](THIRD_PARTY_NOTICES.md)

## Scope and roadmap

Version 0.6.0 deliberately excludes overclocking, GPU/MUX switching, animated
RGB firmware effects, firmware flashing, and third-party kernel modules. Static
24-zone gradients and waves use only the verified static report sequence; they
do not claim or send an animation command. New hardware support requires its
own reversible evidence.

## Alpha disclaimer

This is independent community **alpha** software. It changes fan, power,
platform-profile and keyboard-lighting state. Use it at your own risk; monitor
temperatures, do not bypass hardware checks, and return to firmware control if
behavior is unexpected. To the maximum extent allowed by law, the authors and
contributors accept no liability for damage, data loss, overheating, reduced
performance, or other consequences of use. Lenovo does not endorse, support or
affiliate with this project.

## License

Legion Control is available under the [MIT License](LICENSE). Lenovo and Legion
are trademarks of their respective owners. The MIT license provides the full
no-warranty and limitation-of-liability terms. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for protocol research and
other attributions.
