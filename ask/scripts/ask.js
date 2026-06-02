#!/usr/bin/env node

const fs = require('fs');
const fsp = require('fs/promises');
const path = require('path');
const process = require('process');
const { spawnSync } = require('child_process');

const PROVIDER_BINARIES = {
    claude: 'claude',
    gemini: 'gemini',
    codex: 'codex',
};

const SAFE_ROLE_PATTERN = /^[a-z][a-z0-9-]*$/;

function usage() {
    console.error('Usage: node ask.js <claude|gemini|codex> <question or task>');
    console.error('   or: node ask.js <claude|gemini|codex> --prompt "<prompt>"');
    console.error('   or: node ask.js <claude|gemini|codex> --agent-prompt <role> "<prompt>"');
    console.error('   or: node ask.js <claude|gemini|codex> --agent-prompt=<role> --prompt "<prompt>"');
}

function slugify(value) {
    return value
        .toLowerCase()
        .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 80) || 'task';
}

function timestampToken(date = new Date()) {
    return date.toISOString().replace(/[:.]/g, '-');
}

function parseArgs(argv) {
    const [providerRaw, ...rest] = argv;
    const provider = (providerRaw || '').toLowerCase();
    if (!provider || !Object.prototype.hasOwnProperty.call(PROVIDER_BINARIES, provider)) {
        usage();
        throw new Error(`Invalid provider "${providerRaw || ''}". Expected claude, gemini, or codex.`);
    }

    if (rest.length === 0) {
        usage();
        throw new Error('Missing prompt text.');
    }

    let agentPromptRole;
    let prompt = '';

    for (let index = 0; index < rest.length; index += 1) {
        const token = rest[index];

        if (token === '--agent-prompt') {
            const role = rest[index + 1]?.trim();
            if (!role || role.startsWith('-')) {
                throw new Error('Missing role after --agent-prompt.');
            }
            agentPromptRole = role;
            index += 1;
            continue;
        }

        if (token.startsWith('--agent-prompt=')) {
            const role = token.slice('--agent-prompt='.length).trim();
            if (!role) {
                throw new Error('Missing role after --agent-prompt=');
            }
            agentPromptRole = role;
            continue;
        }

        if (token === '-p' || token === '--prompt' || token === '--print') {
            prompt = rest.slice(index + 1).join(' ').trim();
            break;
        }

        if (token.startsWith('-p=') || token.startsWith('--prompt=') || token.startsWith('--print=')) {
            const inlinePrompt = token.split('=').slice(1).join('=').trim();
            const remainder = rest.slice(index + 1).join(' ').trim();
            prompt = [inlinePrompt, remainder].filter(Boolean).join(' ').trim();
            break;
        }

        prompt = [prompt, token].filter(Boolean).join(' ').trim();
    }

    if (!prompt) {
        usage();
        throw new Error('Missing prompt text.');
    }

    return {
        provider,
        prompt,
        agentPromptRole,
    };
}

function ensureBinary(binary) {
    const probe = spawnSync(binary, ['--version'], {
        stdio: 'ignore',
        encoding: 'utf8',
    });

    if (probe.error && probe.error.code === 'ENOENT') {
        throw new Error(`Missing required local CLI binary: ${binary}. Please install it and verify with "${binary} --version".`);
    }
}

async function readAgentPrompt(role, promptsDir) {
    const normalizedRole = role.trim().toLowerCase();
    if (!SAFE_ROLE_PATTERN.test(normalizedRole)) {
        throw new Error(`Invalid --agent-prompt role "${role}". Expected lowercase role names like "code-reviewer".`);
    }

    const promptPath = path.join(promptsDir, `${normalizedRole}.md`);
    if (!fs.existsSync(promptPath)) {
        const availableRoles = fs.existsSync(promptsDir)
            ? (await fsp.readdir(promptsDir))
                .filter((fileName) => fileName.endsWith('.md'))
                .map((fileName) => fileName.slice(0, -3))
                .sort()
            : [];
        const availableSuffix = availableRoles.length > 0
            ? ` Available roles: ${availableRoles.join(', ')}.`
            : '';
        throw new Error(`Role prompt "${normalizedRole}" not found in ${promptsDir}.${availableSuffix}`);
    }

    const content = (await fsp.readFile(promptPath, 'utf8')).trim();
    if (!content) {
        throw new Error(`Role prompt "${normalizedRole}" is empty: ${promptPath}`);
    }

    return content;
}

function buildLaunchArgs(provider, finalPrompt) {
    if (provider === 'claude') {
        return ['-p', '--', finalPrompt];
    }

    if (provider === 'codex') {
        return [
            'exec',
            '--skip-git-repo-check',
            '--sandbox',
            'read-only',
            finalPrompt,
        ];
    }

    return ['-p', finalPrompt];
}

function buildSummary(exitCode, output) {
    if (exitCode === 0) {
        return 'Provider completed successfully. Review the raw output for details.';
    }

    const firstLine = output
        .split('\n')
        .map((line) => line.trim())
        .find(Boolean);

    return firstLine
        ? `Provider command failed (exit ${exitCode}): ${firstLine}`
        : `Provider command failed with exit code ${exitCode}.`;
}

function buildActionItems(exitCode) {
    if (exitCode === 0) {
        return [
            'Review the response and extract decisions you want to apply.',
            'Capture follow-up implementation tasks if needed.',
        ];
    }

    return [
        'Inspect the raw output error details.',
        'Fix CLI, auth, or environment issues and rerun the command.',
    ];
}

async function writeArtifact({ artifactDir, provider, originalTask, finalPrompt, rawOutput, exitCode }) {
    const slug = slugify(originalTask);
    const timestamp = timestampToken();
    const artifactPath = path.join(artifactDir, `${provider}-${slug}-${timestamp}.md`);
    const summary = buildSummary(exitCode, rawOutput);
    const actionItems = buildActionItems(exitCode);
    const body = [
        `# ${provider} ask artifact`,
        '',
        `- Provider: ${provider}`,
        `- Exit code: ${exitCode}`,
        `- Created at: ${new Date().toISOString()}`,
        '',
        '## Original task',
        '',
        originalTask,
        '',
        '## Final prompt',
        '',
        finalPrompt,
        '',
        '## Raw output',
        '',
        '```text',
        rawOutput || '(no output)',
        '```',
        '',
        '## Concise summary',
        '',
        summary,
        '',
        '## Action items',
        '',
        ...actionItems.map((item) => `- ${item}`),
        '',
    ].join('\n');

    await fsp.mkdir(artifactDir, { recursive: true });
    await fsp.writeFile(artifactPath, body, 'utf8');
    return artifactPath;
}

async function main() {
    const parsed = parseArgs(process.argv.slice(2));
    const scriptDir = __dirname;
    const skillRoot = path.resolve(scriptDir, '..');
    const promptsDir = path.join(skillRoot, 'prompts');
    const artifactDir = path.join(process.cwd(), '.artifacts', 'ask');

    const binary = PROVIDER_BINARIES[parsed.provider];
    ensureBinary(binary);

    let finalPrompt = parsed.prompt;
    if (parsed.agentPromptRole) {
        const rolePrompt = await readAgentPrompt(parsed.agentPromptRole, promptsDir);
        finalPrompt = `${rolePrompt}\n\n${parsed.prompt}`;
    }

    const run = spawnSync(binary, buildLaunchArgs(parsed.provider, finalPrompt), {
        encoding: 'utf8',
        maxBuffer: 10 * 1024 * 1024,
    });

    const stdout = run.stdout || '';
    const stderr = run.stderr || '';
    const rawOutput = [stdout, stderr].filter(Boolean).join(stdout && stderr ? '\n\n' : '');
    const exitCode = typeof run.status === 'number' ? run.status : 1;

    if (stdout) {
        process.stdout.write(stdout);
    }
    if (stderr) {
        process.stderr.write(stderr);
    }

    const artifactPath = await writeArtifact({
        artifactDir,
        provider: parsed.provider,
        originalTask: parsed.prompt,
        finalPrompt,
        rawOutput,
        exitCode,
    });

    process.stdout.write(`\n[ask] artifact: ${artifactPath}\n`);

    if (run.error) {
        throw new Error(run.error.message);
    }

    if (exitCode !== 0) {
        process.exit(exitCode);
    }
}

main().catch((error) => {
    console.error(`[ask] ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
});
