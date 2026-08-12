# Lenovo/ITE `048d:c195` RGB Protocol Notes

## Status and scope

This document records the feature-report path physically validated on one
Lenovo Legion Pro 5 16IAX10H (`83LU`) running Ubuntu 26.04, Linux 7.0, and BIOS
`Q6CN79WW`.

It is not a generic Lenovo, ITE, Legion, or HID LampArray specification. The
implementation intentionally refuses other products, USB IDs, and interfaces.
Protocol names below describe observed behavior; unknown constant fields remain
opaque rather than being assigned invented semantics.

## Controller identity

The working endpoint has these observed properties:

| Property | Value |
|---|---|
| DMI product | `83LU` |
| USB vendor:product | `048d:c195` |
| Linux HID ID | `0003:0000048D:0000C195` |
| USB interface | `00` |
| HID usage page | `0xFF89` (vendor-defined) |
| HID usage | `0x07` |
| feature report ID | `0x07` |
| descriptor feature payload count | 959 bytes |
| userspace report buffer | 960 bytes, including report ID |

The implementation searches `/sys/class/hidraw`, resolves each device inside
`/sys`, matches the HID ID and interface, checks the descriptor signature for
the vendor usage and report ID, and then opens the corresponding `/dev/hidrawN`
with read/write, close-on-exec, and no-follow flags. Before any write, it uses
the opened file descriptor to re-read the raw USB VID/PID and report descriptor.
This rejects a different controller substituted between discovery and `open`.

Interface `01`, which exposes HID LampArray behavior on the tested laptop, is
not the working static-profile transport. An ioctl can succeed on the wrong
interface without producing a visible lighting change; transport acceptance is
not sufficient evidence of protocol compatibility.

## Feature-report envelope

Each report is exactly 960 bytes:

```text
offset  size  meaning
0       1     report ID: 0x07
1       1     command
2       2     payload length, unsigned little-endian
4       N     command payload
4+N     ...   zero padding to 960 bytes
```

Reports are sent with `HIDIOCSFEATURE(960)`. The writer requires the ioctl to
return 960, sends the complete sequence on one open file descriptor, and waits
10 ms between reports.

## Static 24-zone apply

An enabled static configuration uses three reports in order:

1. `C8` — select controller profile `1`.
2. `CB` — save the static zone groups into profile `1`.
3. `CE` — set raw brightness.

The profile-selection prefix is:

```text
07 C8 01 00 01
```

The `CB` payload starts with:

```text
01 01 01
```

Colors with the same RGB value are grouped to keep the report bounded. Each
group is encoded as:

```text
group_id
06 01 0B 02 02 03 00 04 00 05 02 06 00 01
red green blue
led_count
led_id_1_le16 ... led_id_n_le16
```

`group_id` starts at `1`. Logical LED IDs are `1..24`. The fourteen constant
bytes after `group_id` are reproduced as confirmed opaque protocol fields; this
project does not claim names or meanings for them.

The payload length in bytes `2..3` covers the three leading `CB` fields plus all
encoded groups. A solid color therefore uses one group. Twenty-four distinct
colors also fit within the 960-byte report.

The brightness report is:

```text
07 CE 01 00 LEVEL
```

`LEVEL` is an integer from `1` to `9`. A UI percentage is scaled and rounded to
that range. A percentage of `0`, or disabled lighting, follows the off sequence
instead of sending `CE`.

## Off sequence

Off uses two reports:

```text
07 C8 01 00 01
07 CB 03 00 01 01 01
```

Both are padded to 960 bytes. The saved application configuration retains its
24 colors so they can be reused when lighting is enabled again.

## Software-rendered animation

Animated effects are rendered by this project, not by the controller. Each
frame is an ordinary static configuration sent through the sequence documented
above. **No animation, effect-type, speed, or direction command is claimed or
sent.** The fourteen constant bytes inside every colour group are reproduced
unchanged on every frame, exactly as for a static preset.

This distinction is the whole reason the feature exists in this form. Versions
`0.4.5`–`0.4.7` were withdrawn for assuming semantics the hardware had not
confirmed. Naming one of those opaque bytes an "effect selector" and sweeping
its values would repeat that mistake, so the project animates with the report
sequence it has actually verified instead.

Frames are written by a root service, `legion-control-rgbd`, because a
`pkexec` round trip per frame would spawn a privileged process many times a
second. The service:

- opens the same validated `/dev/hidrawN` once and runs the same VID/PID and
  descriptor checks on that descriptor;
- sends `C8` and `CE` once, when the session opens, since profile selection and
  brightness do not change between frames;
- sends only the `CB` colour report per frame, at 12.5 frames per second;
- skips a frame whose 24 colours are identical to the previous one;
- reopens the controller at most once, to survive a USB re-enumeration after
  resume, and then fails rather than retrying indefinitely;
- writes the last saved static configuration back when it stops.

Effects are pure functions of their settings and the elapsed time, so a
restarted service resumes the same animation rather than a different one.

A static write and an animation must never share the controller. The helper
stops the effect service before applying a static configuration, and
`systemctl disable --now` returns only after the service's restore step has
finished, which orders the two writers.

### Measured cost

Measured on the validated unit, as the median of twenty `HIDIOCSFEATURE` calls
on one open descriptor:

| Report | Median | Notes |
|---|---|---|
| `C8` select profile | 5.97 ms | |
| `CE` set brightness | 5.90 ms | |
| `CB` one colour group | 42.02 ms | fastest observed 8.73 ms |
| `CB` twenty-four groups | 56.40 ms | |

A sustained burst of 200 twenty-four-group frames, sent as fast as the
controller accepted them, held steady at 56.51 ms median over its first half
against 56.52 ms over its second, and 67.27 ms at the 95th percentile. Nothing
degraded within that burst, but every frame missed a 20 fps deadline: the
controller tops out near **17 frames per second** when saturated.

Those figures describe back-pressure, not the intrinsic cost. Running the
service paced at 12.5 frames per second on the same unit, the median frame fell
to 16–23 ms, and every effect held its target:

| Effect | Frames/s | Median frame | CPU |
|---|---|---|---|
| breathing | 10.7 | 8.8 ms | 0.31 % |
| rainbow | 12.1 | 22.6 ms | 0.35 % |
| wave | 12.2 | 15.8 ms | 0.37 % |
| comet | 12.3 | 19.2 ms | 0.37 % |
| fire | 12.1 | 22.7 ms | 0.36 % |
| aurora | 12.1 | 22.6 ms | 0.36 % |

A frame whose 24 zones share one colour is cheapest, because the cost tracks
the number of distinct colour groups rather than the constant 960-byte report
size. Breathing falls below its target for a different reason: consecutive
frames round to the same 24 colours and are skipped.

The service therefore paces itself at 12.5 frames per second. Asking for more
only saturates the controller, triples the per-frame cost, and writes more
often.

### Controller wear

Command `CB` is described in this document as saving zone groups into profile
`1`. Whether that write reaches non-volatile storage **is not established**,
and it matters: a page-programming write repeated many times a second would be
a durability problem rather than a performance one.

The measurement above does not settle it. `CB` costing seven to ten times `C8`
or `CE`, and growing with the number of groups, is consistent with programming
storage per group. It is equally consistent with pushing 24 LED values over an
internal bus, which is volatile. The two hypotheses predict the same latency
profile, so this evidence cannot distinguish them.

The test that would distinguish them is persistence across a full power loss:
apply a distinctive static frame, shut down, disconnect power, and observe
whether the controller still shows it. That has not been performed.

Until it is, animation is treated as carrying an unquantified wear risk. It is
opt-in, never starts on its own, and stops whenever any static change is
applied.

## Concurrency and persistence

The root helper serializes privileged operations with
`/run/lock/legion-control.lock`. The RGB writer also holds a process-local lock
for the full feature-report sequence. Configuration is atomically stored in
`/var/lib/legion-control/rgb-config.json` only after every report ioctl returns
success. A failed sequence removes the saved file because the controller may be
partially updated and its semantic state is unknown.

Applying a configuration writes controller profile `1` and may replace its
previous contents. Pressing `Fn+Space` can select a different firmware profile
or effect, so the visible keyboard may later differ from the last application
configuration.

There is no reliable full semantic readback. The saved JSON records the last
sequence accepted by the local helper; it is not proof that every zone remains
visibly applied.

## Intentionally unsupported operations

- arbitrary commands or raw caller-provided reports;
- device-path overrides;
- interface `01` LampArray writes;
- firmware animation commands, including any interpretation of the opaque
  constant bytes as an effect, speed, or direction selector;
- controller reads that are not proven safe;
- USB IDs, DMI products, or descriptor families other than the validated path.

Animation rendered by this project from the verified static sequence is
supported and described under
[Software-rendered animation](#software-rendered-animation). It is not a
firmware effect.

## Research provenance

The Python transport is an independent implementation of protocol facts,
informed by public research in OpenRGB and keyRGB and compared with LegionAura's
separate 4-zone approach. No GPL-licensed source code was copied. Full links and
licenses are listed in
[`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

This protocol is reverse-engineered, unofficial, and not endorsed or supported
by Lenovo or ITE.
