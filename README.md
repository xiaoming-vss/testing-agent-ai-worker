# Testing Agent AI Worker

`testing-agent-ai-worker` is a polling-based Python worker that generates API,
functional, and UI test cases, requirement analysis results, and test reports
for the testing agent platform.

## Runtime choices

- Package/environment manager: `uv`
- Python version: `3.13`
- Service shape: polling worker
- External API: none

## Current structure

```text
src/testing_agent_ai_worker/app/
src/testing_agent_ai_worker/tasks/
src/testing_agent_ai_worker/worker/
src/testing_agent_ai_worker/platform/
src/testing_agent_ai_worker/nanobot_runtime/
tests/unit/tasks/
```

Task-specific business behavior lives under
`src/testing_agent_ai_worker/tasks/<task_type>/`. The worker layer only handles
polling, lifecycle, and dispatch. The platform layer only adapts HTTP protocol
payloads. Shared nanobot config, path, and prompt helpers live under
`nanobot_runtime`.

## Local commands

Create or refresh the environment with `uv`, then run tests from the local
virtual environment:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Run the minimal nanobot SDK demo:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m testing_agent_ai_worker.cli.nanobot_demo
```

Run the two-step nanobot chain demo:

```powershell
$env:NANOBOT_OPENAPI_JSON_PATH = "D:\tmp\openapi.json"
uv run testing-agent-ai-chain-demo
```

Run the worker with the checked-in `config/worker.toml`:

```powershell
uv run testing-agent-ai-worker
```

Before connecting to a platform, provide runtime values through environment
variables. The checked-in file intentionally contains no credential and uses
the portable `runtime/` directory for nanobot data:

```powershell
$env:TESTING_AGENT_PLATFORM_BASE_URL = "https://platform.example.com"
$env:TESTING_AGENT_WORKER_TOKEN = "<worker-token>"
$env:TESTING_AGENT_NANOBOT_RUNTIME_ROOT = "D:\\nanobot-runtime"
```

Never commit provider API keys or worker tokens.

## Docker

Build the production image from the repository root:

```powershell
docker build --tag testing-agent-ai-worker:dev .
```

Run the worker with platform configuration supplied at runtime. The platform
URL must be reachable from inside the container; on Docker Desktop, use
`host.docker.internal` instead of `127.0.0.1` for a service running on the host:

```powershell
docker run --detach `
  --name testing-agent-ai-worker `
  --restart unless-stopped `
  --env TESTING_AGENT_PLATFORM_BASE_URL=http://host.docker.internal:9000 `
  --env TESTING_AGENT_WORKER_TOKEN=<worker-token> `
  --volume testing-agent-runtime:/data/runtime `
  --volume testing-agent-logs:/app/logs `
  testing-agent-ai-worker:dev
```

The image runs as the non-root user `worker` (`uid=10001`) and stores mutable
nanobot data under `/data/runtime`. Logs are written to `/app/logs` as well as
the container console according to `config/worker.toml`.

The worker defaults to long-running polling. Set `[worker].run_once = true` in
`config/worker.toml` when you want a single polling cycle for local debugging.

The platform lifecycle callbacks are wired in for claimed tasks:

- `started`
- background `heartbeat`
- optional `progress`
- final `completed`

The current worker already wires `api_case_generate` into a real two-step
nanobot chain:

- `openapi-test-config-extractor`
- `api-cases-yaml-generator`

For `api_case_generate` tasks, the worker now:

- sends `started`
- reports extractor output through `progress.configJson`
- sends `completed` with `configJson` and final `resultYaml`

Before executing a claimed task, the worker now syncs the task project's
platform skill packages into the nanobot workspace:

- calls `/internal/ai-worker/projects/{projectId}/skills`
- downloads each package through its `downloadUrl`
- extracts the archive into `runtime_root/workspaces/project-{projectId}/skills`
- skips re-download when the local package manifest still matches platform
  `hash`, `size`, and `version`

The worker also supports `functional_case_generate` for `source_type=text` and
`source_type=word` through a three-step nanobot chain. In both cases it uses
`sourceContent` as the text input and does not download a source file:

- `solution-test-point-analyzer`
- `test-case-name-extractor`
- `detailed-test-case-generator`

For `functional_case_generate` text tasks, the worker now:

- sends `started`
- reports `requirement_analysis` progress with intermediate `configJson`
- reports `case_names` progress with intermediate `configJson`
- splits the final detailed-case generation by `caseNames.categories[].model`
- reports `detailed_cases` progress as batches finish and merged `cases` accumulate
- sends `completed` with final detailed test case JSON in `resultYaml`

When `checkpointEnabled=true`, the worker also supports staged resume for
functional text tasks:

- `requirement_analysis` -> analyzes `sourceContent` and writes `waiting_review`
  progress with `configJson.requirementAnalysis`
- `case_names` -> resumes from `configJson.requirementAnalysis`
- `detailed_cases` -> resumes from `configJson.caseNames`, reports batch
  progress, and only then sends `completed`

The worker now also recognizes `requirement_analysis` for
`documentType=text` and `documentType=word` through a three-step nanobot chain.
`richtext` is not supported:

- `extract-docx-enhanced-text`
- `prd-requirement-writing-skill`
- `prd-feature-understanding-skill`

For `requirement_analysis` tasks, the worker:

- sends `started`
- downloads `documentDownloadUrl` into the task workspace with the worker token,
  then passes the saved local file path to `extract-docx-enhanced-text`
- reports `analyzing` progress after the first skill step
- sends `completed` with the third skill output in `resultYaml`

Other task types, functional tasks with unsupported `source_type`, or
requirement-analysis tasks with unsupported `documentType`, still return explicit
failures after being claimed.

The worker also supports `ui_case_generate`: it downloads the ZIP source archive
from `sourceArchiveDownloadUrl`, safely extracts it, runs `generate-ui-test-case`,
and requires a non-empty YAML list as the result.

For `test_report_generate`, the worker passes `dailyMetrics` to
`advanced-test-report-generator` and returns the generated report text.

If you want to call the demo directly from Python, pass the values as function
arguments:

```python
import asyncio

from testing_agent_ai_worker.cli.nanobot_demo import run_cli_demo


asyncio.run(
    run_cli_demo(
        message="What time is it in Tokyo?",
        session_key="demo:nanobot",
        config_path=r"C:\Users\you\.nanobot\config.json",
        workspace=r"D:\path\to\workspace",
    )
)
```

If you want to call the two-step chain demo directly from Python:

```python
import asyncio

from testing_agent_ai_worker.cli.nanobot_chain_demo import run_chain_demo


asyncio.run(
    run_chain_demo(
        openapi_json_path=r"D:\tmp\openapi.json",
        session_key="demo:nanobot-chain",
        extra_instruction="只生成登录与用户信息相关接口的测试配置",
    )
)
```

The chain demo uses skill names directly in the nanobot prompt:

- `openapi-test-config-extractor`
- `api-cases-yaml-generator`

It does not read local `SKILL.md` files.

## code_risk_analysis development verification (skill stub)

The platform-side `code-risk-analysis` skill package is not ready yet, so the worker supports two modes:

- **Unit tests**: the executor injects a fake skill runner (see `tests/unit/tasks/code_risk_analysis/test_executor.py`).
- **Local stub (end-to-end)**: place a stub skill under the task workspace `skills` dir:

```text
<runtime_root>/workspaces/project-<projectId>/skills/code-risk-analysis/SKILL.md
```

The stub's only job is to return the four-section YAML report (`changeOverview` / `risks` / `affectedCases` / `coverageGaps`) for the given input (requirement understanding record + per-repo diff blocks + existing test cases). A minimal `SKILL.md` can just state that the agent must output exactly that YAML shape with per-repository `baselineCommit`/`headCommit`. The worker knows only the skill name and never depends on its content. Before running, the worker syncs the project skill space; if the `code-risk-analysis` directory is still missing it fails with "项目未配置 code-risk-analysis 技能包" instead of running blind.

Manual end-to-end steps:

1. Optionally set `[code_risk_analysis].gitlab_timeout_seconds` (default 120) in `config/worker.toml` to tune the GitLab compare timeout.
2. Create the stub directory above with a minimal `SKILL.md` before starting the worker.
3. Create a `code_risk_analysis` task on the platform (the requirement must have finished requirement analysis so a requirement understanding record exists).
4. Start the worker with `run_once = true`; the logs should show `fetching_diff` then `analyzing` progress and a final `completed` callback.
5. Success path: `resultYaml` has the four sections with per-repository baseline/head SHA. Failure paths: `errorMessage` and `remediation` are readable (missing understanding record, unavailable credentials, missing skill package, repo diff failure).

Once the real skill package is uploaded to the project skill space, the existing hash/size/version sync replaces the stub automatically — no worker code change.

## Next steps

- add integration tests against a real platform environment
- add local failure persistence and retry auditing
- add runtime metrics and task-level observability
