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

## Static patterns, and why animation is not implemented

Legion Control ships patterns richer than a flat gradient — aurora, fire, a
comet, a crest, colour bands — by sampling a continuous field at one phase and
writing that single frame through the sequence above. One preset, one write.

Animating them by resending successive phases was built and then removed. The
reasoning is recorded here because the measurements are the useful part.

### Measured cost

Median of twenty `HIDIOCSFEATURE` calls on one open descriptor, on the
validated unit:

| Report | Payload | Median |
|---|---|---|
| `C8` select profile | 1 byte | 6.03 ms |
| `CB` off | 3 bytes, no colour | 37.67 ms |
| `CB` one colour group | one colour | 37.50 ms |
| `CB` twenty-four groups | 24 colours | 47.02 ms |
| `CE` set brightness | 1 byte | 5.90 ms |

The cost belongs to the `CB` command, not to its contents. The off report
carries no colour at all and still costs as much as a coloured one. The first
`CB` after a pause completes in about 7 ms and later ones in about 37 ms, which
reads as controller back-pressure rather than per-byte work.

Driven as fast as it accepted them, the controller sustained about 17 frames per
second, holding steady across a 200-frame burst: 56.51 ms median over the first
half against 56.52 ms over the second. Paced at 12.5 frames per second instead,
the median frame fell to 16–23 ms and the whole animation cost about 0.36 % of
one CPU.

### Controller wear: unresolved

Command `CB` is described above as saving zone groups into profile `1`. Whether
that write reaches non-volatile storage **could not be determined**, and it
decides whether continuous animation is safe: at 12.5 frames per second, even a
100k-cycle part would be exhausted in roughly 2.2 hours of use.

Two experiments were run on the validated unit.

*Persistence.* A marker frame of eight zones pure red, eight pure green and
eight pure blue survived two full power cycles, and a later all-white frame at
raw brightness level 1 survived a third. This was verified rather than assumed:
the journal shows `systemd-poweroff.service` and `poweroff.target`,
`/var/lib/legion-control/rgb-config.json` kept its pre-shutdown mtime, and no
application process or service was running. A live blink test confirmed the
writes reach the visible keyboard. The controller retains colour and brightness
across S5 — but a laptop normally keeps that controller powered from the
internal battery in S5, and the rail cannot be cut without disassembly, so
survival does not establish flash.

*Latency.* An early reading of the timings above suggested the expense was
storing colour data. The off report refutes it: no colour, same cost. A
fixed-cost profile refresh and a fixed-cost page program are indistinguishable
from here.

So the question stays open, and one asymmetry settles the decision instead. The
firmware animates the keyboard by itself through `Fn+Space`, so a path that does
not wear anything must exist inside it — reached by one of the opaque constant
bytes this project refuses to guess at. Shipping continuous animation and being
wrong damages the controller permanently; withholding it costs motion, and the
patterns survive as still frames.

Anyone repeating this on their own hardware should start from the persistence
test, and should cut power to the controller properly before concluding
anything.

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
- animation of any kind, whether by a firmware command or by resending frames;
- any interpretation of the opaque constant bytes as an effect, speed, or
  direction selector;
- controller reads that are not proven safe;
- USB IDs, DMI products, or descriptor families other than the validated path.

Static patterns rendered by this project from the verified static sequence are
supported and described under
[Static patterns](#static-patterns-and-why-animation-is-not-implemented). They
are single frames, not effects.

## Research provenance

The Python transport is an independent implementation of protocol facts,
informed by public research in OpenRGB and keyRGB and compared with LegionAura's
separate 4-zone approach. No GPL-licensed source code was copied. Full links and
licenses are listed in
[`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

This protocol is reverse-engineered, unofficial, and not endorsed or supported
by Lenovo or ITE.
