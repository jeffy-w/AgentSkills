---
name: ios-device-build-run
description: Build, install, launch, and inspect runtime logs for iOS apps on physical devices from Codex. Use when a user asks to build and run an iOS app on a real iPhone/iPad, capture live xcodebuild/devicectl/device logs, avoid launch hangs from already-running apps, read previous run logs, or filter/search iOS build and runtime logs without dumping huge files.
---

# iOS Device Build Run

Use the bundled script for repeatable real-device build/run/log workflows:

```bash
python3 ios-device-build-run/scripts/ios_device_build_run.py <subcommand> [options]
```

The script stores durable sessions under:

```text
~/.codex/ios-device-build-run/sessions/<timestamp>-<scheme>/
```

Each session may contain `build.raw.log`, `build.pretty.log`, `install.log`, `run.log`, `device.log`, `metadata.json`, `events.jsonl`, `pids.json`, and devicectl JSON outputs.

## Workflow

1. Run `doctor` if the environment is unknown:
   ```bash
   python3 ios-device-build-run/scripts/ios_device_build_run.py doctor
   ```
2. Prefer `build-run` for the normal path:
   ```bash
   python3 ios-device-build-run/scripts/ios_device_build_run.py build-run
   ```
3. Device auto-selection prefers wired USB devices. If exactly one wired device is connected, it is used automatically; otherwise pass `--device <udid-or-name>`.
4. Read logs through the script instead of dumping whole files:
   ```bash
   python3 ios-device-build-run/scripts/ios_device_build_run.py logs --session latest --file build --tail 200
   python3 ios-device-build-run/scripts/ios_device_build_run.py logs --session latest --file device --grep EffectEngine --tail 300
   python3 ios-device-build-run/scripts/ios_device_build_run.py logs --session latest --file all --search 'error|fatal|crash' --ignore-case --context 3
   ```
5. Stop background runtime logging when done:
   ```bash
   python3 ios-device-build-run/scripts/ios_device_build_run.py stop-log --session latest
   ```

## Subcommands

- `doctor`: verify `xcodebuild`, `xcrun`, optional `idevicesyslog`, optional `xcbeautify`, and connected physical devices.
- `devices`: list available physical iOS devices; simulators are excluded.
- `build`: build only, create a session, locate the `.app`, and read `CFBundleIdentifier` from `Info.plist`.
- `install`: install an existing or latest-session `.app` onto a physical device.
- `run`: launch an already-installed app from a session or explicit `--bundle-id`.
- `build-run`: build, locate app, install, start runtime log stream, then launch.
- `log-stream`: start only runtime log capture for a session.
- `logs`: filter/search/tail persisted logs.
- `stop-log`: terminate the background runtime log process recorded in `pids.json`.
- `sessions`: list recent sessions.

## Defaults and discovery

- Workspace/project selection:
  1. explicit `--workspace` or `--project`;
  2. project-name-matching `.xcworkspace`;
  3. unique `.xcworkspace`;
  4. project-name-matching `.xcodeproj`;
  5. unique `.xcodeproj`;
  6. otherwise stop and list candidates.
- Scheme selection:
  1. explicit `--scheme`;
  2. scheme matching workspace basename;
  3. scheme matching repo/project name;
  4. unique shared scheme;
  5. otherwise stop and list candidates.
- Configuration defaults to `Debug`.
- Build destination defaults to `generic/platform=iOS` for arm64 physical-device builds.
- Build uses a session-local `-derivedDataPath` so `.app` discovery and logs are reproducible.
- Device selection prefers wired USB physical devices. If exactly one wired device is available, use it automatically. If multiple wired devices exist, stop and require `--device`. If no wired device exists, auto-pick only when exactly one physical device is available; otherwise require `--device` or ask the user to connect exactly one USB device.

For an app repository with no parameters, this should resolve to the matching `.xcworkspace` or `.xcodeproj`, matching scheme, configuration `Debug`, and destination `generic/platform=iOS` when discovery is unambiguous.

### Device priority

Prefer wired USB devices over network/Wi-Fi devices because they are usually more stable for install, launch, and runtime log capture. With no `--device`:

1. exactly one wired physical iOS device -> use it automatically;
2. multiple wired physical iOS devices -> stop and list wired candidates;
3. no wired device and exactly one physical iOS device -> use it;
4. no wired device and multiple network/Wi-Fi devices -> stop and require `--device` or a USB connection.

`doctor` and `devices` show each device's `interface` so the agent can explain why auto-selection did or did not happen.

## Launch and already-running apps

`build-run` and `run` launch with devicectl `--terminate-existing` by default to avoid the known hang when the app is already running. Pass `--no-terminate-existing` only when preserving the current process is required.

Do not implement ad-hoc PID killing unless launch fallback is needed. Current devicectl supports `device process launch --terminate-existing`; `device process terminate` requires `--pid`.

## Runtime logs

Runtime log capture starts after install and before launch in `build-run`, so launch-time logs and early crashes are captured.

Priority:

1. `idevicesyslog` if installed. The script uses `--udid`, `--no-colors`, and `--output device.log`; it adds a process filter when `--process-name` is passed, otherwise a bundle-id match when possible.
2. If `idevicesyslog` is missing, continue with `run.log`/devicectl logs and report that `device.log` is unavailable. Treat this as an environment limitation, not an app failure.
3. Future devicectl log-stream support may be used as a fallback, but verify local `xcrun devicectl ... --help` before relying on it.

Runtime logging is non-blocking by default. It continues in the background until `stop-log`, session cleanup, or optional `--log-duration <seconds>`.

## Build logs and xcbeautify

The script always preserves raw xcodebuild output as `build.raw.log`.

If `xcbeautify` is installed, default `--beautify auto` also writes `build.pretty.log` and prints a readable summary. Use:

```bash
--beautify auto|always|never
--xcbeautify-renderer terminal|github-actions|teamcity|azure-devops-pipelines
```

Use raw logs for machine search and diagnosis; use pretty logs for human-facing summaries. Do not run `xcbeautify` over `device.log` or `run.log`.

## Log filtering contract

Prefer `logs` over `cat` to reduce token use:

```bash
python3 ios-device-build-run/scripts/ios_device_build_run.py logs --session latest --file build --tail 200
python3 ios-device-build-run/scripts/ios_device_build_run.py logs --session latest --file device --grep 'AppName' --ignore-case --max-lines 120
python3 ios-device-build-run/scripts/ios_device_build_run.py logs --session latest --file all --search 'error|warning|fatal|crash' --context 2 --line-numbers
```

Supported selectors:

- `--file build|pretty|run|device|all`
- `--tail N`
- `--grep TEXT`
- `--search REGEX`
- `--ignore-case`
- `--since TIMESTAMP`
- `--context N`
- `--max-lines N` (default 300)
- `--line-numbers`

## Xcode MCP note

If a project instruction prefers Xcode MCP and the user only asks for a build, MCP may be used. When the task requires durable real-time logs, session history, install/run, or filtered runtime logs, use this script's CLI workflow because it persists raw logs, metadata, and background log process state.

## Failure handling

- Separate source failures from environment failures such as missing CocoaPods files, locked build databases, unavailable devices, provisioning issues, or missing `idevicesyslog`.
- On build failure, read a focused slice first:
  ```bash
  python3 ios-device-build-run/scripts/ios_device_build_run.py logs --session latest --file build --search 'error:|fatal error:|BUILD FAILED' --ignore-case --context 4 --max-lines 160
  ```
- Always report the session path so the user or a later agent can inspect logs after the run.
