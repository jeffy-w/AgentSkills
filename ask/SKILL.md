---
name: ask
description: Use when you need a local external advisor CLI, such as asking Claude, Gemini, or Codex for focused questions, reviews, brainstorming, or second opinions, while saving a reusable markdown artifact.
---

# Ask

使用本 skill 时，直接调用本机安装的 `claude`、`gemini` 或 `codex` CLI，并把结果保存为可复用 artifact。

## When to use

- 用户明确说要使用本地顾问 CLI 能力。
- 需要本地 Claude / Gemini 做一轮 review、二次确认、brainstorming。
- 需要保留原始任务、最终 prompt、原始输出和 action items。

## Script

主脚本：

```text
ask/scripts/ask.js
```

## Direct usage

```bash
node ask/scripts/ask.js claude "请 review 当前改动"
node ask/scripts/ask.js gemini --prompt "分析这个 bug 根因"
node ask/scripts/ask.js codex --prompt "给我第二视角分析当前实现"
node ask/scripts/ask.js claude --agent-prompt code-reviewer "请检查这次重构风险"
```

## Behavior

1. 校验 provider 只允许 `claude`、`gemini` 或 `codex`。
2. 可选读取 `prompts/<role>.md`，将角色 prompt 与用户 prompt 拼接。
3. 直接调用本地 CLI：
   - `claude -p -- "<prompt>"`
   - `gemini -p "<prompt>"`
   - `codex exec --skip-git-repo-check --sandbox read-only "<prompt>"`
4. 将输出写入：

```text
.artifacts/ask/<provider>-<slug>-<timestamp>.md
```

artifact 至少包含：

1. Original user task
2. Final prompt
3. Raw CLI output
4. Concise summary
5. Action items

## Role prompts

角色 prompt 目录：

```text
ask/prompts/
```

如果需要新增角色，直接新增同名 `.md` 文件，例如：

- `code-reviewer.md`
- `architect.md`
- `debugger.md`

## Guardrails

- 本 skill 只走本地 CLI，不要静默切换到 MCP 或远端 provider。
- 如果本地 binary 缺失，应直接报错并提示用户安装。
- `codex` provider 默认走非交互 `codex exec`，并使用只读沙箱，适合作为问答 / review / 分析顾问，不适合直接让它改代码。
- 回答时优先总结 artifact 里的结论，再决定是否继续落实现或 review。
