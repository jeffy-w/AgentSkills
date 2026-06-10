# AgentSkills

Shared agent skills repository.

## Skills

### 1. `ask`

Local external advisor skill for `claude`, `gemini`, and `codex` CLI.

- Skill doc: [ask/SKILL.md](ask/SKILL.md)
- Script: [ask/scripts/ask.js](ask/scripts/ask.js)
- Design note: [docs/ask-design-and-implementation.html](docs/ask-design-and-implementation.html)

### 2. `ios-device-build-run`

Build, install, launch, and inspect runtime logs for iOS apps on physical devices from Codex.

- Skill doc: [ios-device-build-run/SKILL.md](ios-device-build-run/SKILL.md)
- Script: [ios-device-build-run/scripts/ios_device_build_run.py](ios-device-build-run/scripts/ios_device_build_run.py)
- Agent metadata: [ios-device-build-run/agents/openai.yaml](ios-device-build-run/agents/openai.yaml)

Use this skill when an agent needs a repeatable real-device iOS workflow with durable build, install, launch, and runtime log artifacts.

Common commands:

```bash
python3 ios-device-build-run/scripts/ios_device_build_run.py doctor
python3 ios-device-build-run/scripts/ios_device_build_run.py devices
python3 ios-device-build-run/scripts/ios_device_build_run.py build-run
python3 ios-device-build-run/scripts/ios_device_build_run.py logs --session latest --file build --tail 200
python3 ios-device-build-run/scripts/ios_device_build_run.py logs --session latest --file all --search 'error|fatal|crash' --ignore-case --context 3
python3 ios-device-build-run/scripts/ios_device_build_run.py stop-log --session latest
```

Session artifacts are stored under:

```text
~/.codex/ios-device-build-run/sessions/<timestamp>-<scheme>/
```

The workflow prefers a single wired USB physical iOS device when no `--device` is passed. Pass `--workspace`, `--project`, `--scheme`, `--configuration`, or `--device` when auto-discovery is ambiguous.
