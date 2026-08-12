# Reliability

Legion Control is a single-user, offline desktop application. Its production
risks are local integration points and hardware state, not network scale.

## Integration-point budget

| Integration | Bound | Failure behavior |
|---|---:|---|
| PolicyKit helper process | 120 s | UI reports cancellation, absence, malformed output, or timeout |
| `systemctl` mutations | 15 s | helper raises a contextual error and runs compensation |
| `systemctl is-active` probes | 5 s | status degrades to inactive instead of hanging |
| NVIDIA temperature fallback | 4 s | GPU temperature becomes unavailable; CPU remains usable when trustworthy |
| fan loop | 2 s interval | every exit attempts firmware restore; systemd repeats it on stop |
| RGB feature reports | 10 ms pacing | one locked FD; partial/failing sequence closes FD and invalidates saved state |

The only outbound network call is the opt-in release notice, disabled by
default: one HTTPS request per day, with an 8 s timeout and a bounded response,
whose every failure mode is the single answer "unknown". It is never retried,
holds no connection, and no hardware, privilege, or safety path depends on it.

There are otherwise no retry loops, remote dependencies, connection pools,
queues, or databases. Circuit breakers and distributed tracing would add
complexity without protecting a real integration point.

## Safe failure states

- Manual fan control safe state: both targets `0` and firmware control active.
- Unsupported or incomplete hardware: mutation refused.
- Critical/missing thermal input: exit `3`, restore, and do not restart-loop.
- Failed combined Custom apply: automatic fan policy, service stopped, previous
  power values and previous non-Custom profile restored on a best-effort basis.
- Failed RGB sequence: FD closed and persisted RGB state removed because the
  visible controller state is unknown.
- Concurrent mutation: rejected in the UI or serialized by the root helper.

## Observability

The daemon emits bounded structured-by-field log lines through journald:
temperature, filtered control temperature, observed fan RPM, and target. It
also records policy reload and firmware restoration. The UI exposes actionable
errors from the helper while avoiding raw command output.

Useful bounded diagnostics are listed in
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md). Logs must be sanitized before they
are shared.

## Deployment and rollback

The supported deployment unit is one Debian package. A local release gate
builds and inspects it without installation. Package removal stops the daemon
and attempts restoration before files disappear; purge removes only the two
known root-owned configuration files.

Starting with 0.5.0, a future upgrade records whether the fan daemon was active,
stops/restores it during replacement, then re-enables it after configuration.
The first upgrade from an older package cannot benefit from an older `prerm`
that did not yet implement this marker; users should verify their mode once.

Rollback target:

```bash
sudo apt remove legion-control
sudo /usr/libexec/legion-control-fand --restore-auto
```

The second command is only available while the package is installed. For
emergency sequencing and final-state checks, follow [`SAFETY.md`](SAFETY.md).

## Capacity decision

Expected load is one UI process, one optional daemon loop, one laptop, and well
under 100 user mutations per day. Configuration files are bounded to 4–8 KiB;
history retains ten minutes in memory. Package and test gates complete in
seconds. Network/load/stress scaling categories are not applicable.

## Evidence still required

- Suspend/resume while a curve is active.
- Sustained combined CPU/GPU load with both fans observed.
- Install → upgrade → remove → purge on a clean disposable Ubuntu system.
- A bounded fan-stall policy based on physical evidence; target readback alone
  does not prove that an impeller is moving.
- First public-user feedback before calling the release stable.

These are explicit release limitations, not assumed successes.
