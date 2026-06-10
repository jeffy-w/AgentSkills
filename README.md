# AgentSkills

Shared agent skills for Claude Code, Cursor, Codex, and other agents that support the [Agent Skills](https://agentskills.io) format.

Repository: https://github.com/jeffy-w/AgentSkills

## Install

Install from [skills.sh](https://skills.sh) via the Skills CLI:

```bash
# Install all skills globally, non-interactive
npx skills add jeffy-w/AgentSkills -g -y

# Install a single skill
npx skills add jeffy-w/AgentSkills@ask -g -y
npx skills add jeffy-w/AgentSkills@ios-device-build-run -g -y
```

| Flag | Meaning |
|------|---------|
| `-g` / `--global` | Install to user-level agent directories (available across projects) |
| `-y` / `--yes` | Skip confirmation prompts |

Browse on skills.sh:

- https://www.skills.sh/jeffy-w/AgentSkills/ask
- https://www.skills.sh/jeffy-w/AgentSkills/ios-device-build-run

> **Note:** skills.sh listing is driven by anonymous install telemetry from `npx skills add`. Local-path installs do not count toward the leaderboard.

### Local development

Clone this repo and install from the working tree while iterating on a skill:

```bash
git clone https://github.com/jeffy-w/AgentSkills.git
cd AgentSkills

npx skills add . --list
npx skills add .@ask -g -y
npx skills add .@ios-device-build-run -g -y
```

After pushing changes to GitHub, reinstall from the remote source to pick up updates:

```bash
npx skills add jeffy-w/AgentSkills -g -y
```

## Skills

### 1. `ask`

Local external advisor skill for `claude`, `gemini`, and `codex` CLI.

- Skill doc: [ask/SKILL.md](ask/SKILL.md)
- Script: [ask/scripts/ask.js](ask/scripts/ask.js)
- Design note: [docs/ask-design-and-implementation.html](docs/ask-design-and-implementation.html)

Use when you need a focused second opinion, review, or brainstorming pass from a local CLI advisor, with output saved as a reusable markdown artifact.

Quick start:

```bash
node ask/scripts/ask.js claude "Review the current changes"
node ask/scripts/ask.js gemini --prompt "Analyze this bug root cause"
node ask/scripts/ask.js codex --prompt "Give a second perspective on this implementation"
```

### 2. `ios-device-build-run`

Build, install, launch, and inspect runtime logs for iOS apps on physical devices.

- Skill doc: [ios-device-build-run/SKILL.md](ios-device-build-run/SKILL.md)
- Script: [ios-device-build-run/scripts/ios_device_build_run.py](ios-device-build-run/scripts/ios_device_build_run.py)
- Agent metadata: [ios-device-build-run/agents/openai.yaml](ios-device-build-run/agents/openai.yaml)

Use when an agent needs a repeatable real-device iOS workflow with durable build, install, launch, and runtime log artifacts.

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

## License

See [LICENSE](LICENSE).
