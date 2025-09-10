## Pluggable Lambda Toolsets for MCP — Architecture & Delivery Spec

### 1) Goals and scope
- Build many toolsets, each deployed as its own AWS Lambda, callable by the MCP server.
- Define tools with `@tool` and Pydantic params/results; expose manifest and RPC invoke.
- Use CodePipeline for CI/CD; CDK for synthesis; no canary (AllAtOnce deployments).
- Separate PyPI package for MCP server stubs.
- Environments: develop→dev, test→test, main→prod with IAM isolation.
- Provide a registry MCP reads to discover toolsets/versions.
- Include a synth script and CloudFormation Hooks.

---

## 2) Environments and branch strategy
- Branch-to-env mapping:
  - develop → dev
  - test → test
  - main → prod
- Per-environment AWS accounts recommended; otherwise, strict per-env IAM and naming.
- Per-env Lambda alias names: `dev`, `test`, `prod`.

### Naming conventions
- Lambda function name: `toolforest-tool-<toolset-name>` (e.g., `toolforest-tool-math`).
- Lambda alias names: `dev`, `test`, `prod`.
- CloudWatch log group: `/aws/lambda/toolforest-tool-<toolset-name>`.
- SSM registry parameter: `/toolforest/<env>/toolsets/<toolset-name>`.

---

## 3) Component architecture

- **Toolset (Lambda)**
  - Code authored with `@tool` functions and Pydantic models.
  - Exposes two actions over invoke:
    - `describe_tools`: returns metadata (name, docstring, ordered params, JSON Schemas).
    - `invoke`: executes a specific tool with validated params.
  - Uses a shared runtime library for handler wiring, schema generation, and error mapping.

- **Shared runtime package (Lambda side)**
  - Provides registry of tools, Pydantic serialization, JSON-RPC-ish envelope, and structured logging.

- **MCP server stubs package (PyPI)**
  - Reads the registry for current env (SSM/AppConfig).
  - Fetches `describe_tools` per toolset alias.
  - Generates local Python stubs with matching `__doc__` and `__signature__`.
  - Invokes Lambdas with retries (Tenacity) and raises mapped exceptions.

- **Registry**
  - Backed by SSM Parameter Store (one parameter per toolset per env) with a well-defined JSON payload.
  - Optionally cached via AppConfig.

---

## 4) Toolset authoring contract

- Pydantic v2 models for params/results:
```python
from pydantic import BaseModel, Field

class AddParams(BaseModel):
  x: float = Field(..., description="First addend")
  y: float = Field(..., description="Second addend")

class AddResult(BaseModel):
  value: float = Field(..., description="Sum")
```

- Tool function with `@tool`:
```python
from mcp.server.fastmcp import tool

@tool
def add(params: AddParams) -> AddResult:
  """Add two numbers."""
  return AddResult(value=params.x + params.y)
```

- Handler RPC surface:
  - `{"action":"describe_tools"}` → list of tool specs (name, doc, ordered fields, schemas).
  - `{"action":"invoke","method":"add","params":{"x":1,"y":2}}` → `{"result":{"value":3}}`.
  - Errors return `{"error":{"type":"...","message":"..."}}`.

---

## 5) Repository layout (monorepo)

- `toolsets/<toolset_name>/`
  - `src/` Lambda code (imports shared runtime)
  - `tests/` unit + contract tests
  - `toolset.yaml` metadata
- `infra/` CDK app (TypeScript or Python) that parses `toolset.yaml` and defines stacks
- `packages/mcp-lambda-runtime/` shared Lambda runtime (optional layer + PyPI)
- `packages/mcp-remote-toolsets/` MCP server stubs package (PyPI)
- `scripts/` helper scripts (e.g., `synth.sh`, local test invokers)
- `pipeline/` buildspecs, CodePipeline definitions (if using CDK Pipelines)

---

## 6) Toolset metadata (`toolset.yaml`)

- Example:
```yaml
toolset_id: "7b7b2a38-269e-4a1f-9dbf-6a85bf2abf4d"  # immutable UUID
name: "math"                                       # unique per account
runtime: "python3.12"
handler: "lambda_handler.handler"
memory_mb: 256
timeout_s: 15
env:
  LOG_LEVEL: "INFO"
permissions:
  - "dynamodb:PutItem"
layers:
  - "arn:aws:lambda:us-west-2:123456789012:layer:mcp-runtime:5"
alarms:
  errors_threshold: 1
  duration_p95_ms: 1000
registry:
  enabled: true
```

- Validation enforced by the synth step and CloudFormation Hooks.

---

## 7) IAM model

- **Lambda execution roles**
  - One per toolset per env, granting only required AWS permissions from `permissions`.

- **MCP server invoke roles**
  - `McpServerRoleDev` can invoke only ARNs of alias `dev` for all toolsets.
  - `McpServerRoleTest` → alias `test`; `McpServerRoleProd` → alias `prod`.

- Example MCP dev policy statement:
```json
{
  "Effect": "Allow",
  "Action": ["lambda:InvokeFunction"],
  "Resource": "arn:aws:lambda:us-west-2:123456789012:function:toolforest-tool-*:dev"
}
```

- Registry read:
  - Allow `ssm:GetParameter` on `/toolforest/dev/toolsets/*` for dev role (similarly for test/prod).

---

## 8) Registry (SSM Parameter Store)

- Path: `/toolforest/<env>/toolsets/<name>`
- Payload example:
```json
{
  "toolset_id": "7b7b2a38-269e-4a1f-9dbf-6a85bf2abf4d",
  "name": "math",
  "lambda_function_arn": "arn:aws:lambda:...:function:toolforest-tool-math",
  "alias": "dev",
  "alias_arn": "arn:aws:lambda:...:function:toolforest-tool-math:dev",
  "version": "17",
  "manifest_version": "2025-09-09T12:34:56Z"
}
```

- Written/updated by the CDK stack at deploy time.

---

## 9) CDK application (synth)

- One stack per toolset per environment: `Toolset-<name>-<env>`.
- Creates:
  - `AWS::Lambda::Function`, `AWS::Lambda::Version`, `AWS::Lambda::Alias` (alias = env).
  - Execution Role and policies from `permissions`.
  - CloudWatch Alarms if configured (errors, duration).
  - SSM Parameter for registry.
- Packaging:
  - Bundle `src/` and vendored deps; prefer a shared Layer for runtime code.
- Synthesis:
  - CDK parses all `toolset.yaml` files; stacks are generated at `cdk synth`.
- Outputs:
  - Lambda function ARN, alias ARN, and version (used for registry write).

- Synth script:
```bash
#!/usr/bin/env bash
set -euo pipefail
export CDK_DEFAULT_ACCOUNT=${CDK_DEFAULT_ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}
export CDK_DEFAULT_REGION=${CDK_DEFAULT_REGION:-us-west-2}
# Optional: pass ENV=dev|test|prod to scope stacks
ENV=${ENV:-dev}
npx cdk synth --quiet
```

---

## 10) CodePipeline design (no canary)

- Trigger: Git webhooks on target branches per env.
- Stages:
  - **Source**: fetch repo on branch.
  - **Detect changes**: determine changed `toolsets/<name>/` (path filter).
  - **Build/Test (parallel per changed toolset)**:
    - Lint/type-check/tests for that toolset.
    - Package Lambda artifact (zip).
  - **Synth**:
    - `cdk synth` to generate CloudFormation templates for all toolsets or changed ones.
  - **Deploy**:
    - CloudFormation deploy (AllAtOnce) for changed stacks only.
  - **Post-deploy**:
    - Smoke tests: invoke `describe_tools`, basic tool call.
  - **Registry update**:
    - SSM written by stack; optional verification step reads and validates entries.
- Artifacts:
  - Packaged zips per toolset, CDK templates in `cdk.out/`.

- Example `buildspec.yml` (per toolset job):
```yaml
version: 0.2
phases:
  install:
    commands:
      - pip install -r requirements.txt
      - pip install -r packages/mcp-lambda-runtime/requirements.txt
  build:
    commands:
      - pytest -q toolsets/$TOOLSET_NAME/tests
      - python -m zipfile -c dist/$TOOLSET_NAME.zip toolsets/$TOOLSET_NAME/src
artifacts:
  files:
    - dist/$TOOLSET_NAME.zip
```

---

## 11) CloudFormation Hooks

- Purpose: enforce deploy-time policies and catch misconfigurations early.
- Validations:
  - Allowed runtimes (`python3.12`).
  - Max timeout/memory.
  - Required alias naming matches env.
  - Alarms present if configured.
  - Tagging requirements: `toolset_id`, `env`, `owner`.
- Registration:
  - Create a Hook (Lambda) once per account/region; CDK can include registration.
- Execution:
  - PreCreate/PreUpdate of `AWS::Lambda::Function`, `AWS::Lambda::Alias`, `AWS::IAM::Role`.

---

## 12) Testing strategy

- Unit tests: pure Python tests per toolset.
- Contract tests: validate `describe_tools` structure and JSON Schema against golden samples.
- Integration tests: in dev account, invoke Lambda via `boto3` using the alias; assert behavior and auth boundaries.
- Smoke tests (post-deploy): single end-to-end tool invocation with typical inputs.

---

## 13) Observability

- Structured logs (JSON): include `toolset`, `tool`, `env`, `request_id`, `duration_ms`, `result_status`.
- Metrics:
  - Success/failure counts, duration, size.
  - Export custom metrics with `put_metric_data` or embedded metric format.
- Alarms:
  - Errors ≥ threshold over N mins.
  - Duration p95 over threshold.
- Tracing:
  - X-Ray optional; be mindful of cost/latency.

---

## 14) Security & compliance

- Least-privilege IAM everywhere (per toolset exec role; per-env MCP invoke role).
- Secrets: SSM/Secrets Manager; no plaintext in `toolset.yaml`.
- VPC: only when needed; account for cold start penalties and NAT costs.
- Artifact integrity: sign Lambda zips or pin dependencies; keep SBOMs for packages.
- Access boundaries:
  - MCP dev/test/prod roles limited to their env’s registry path and alias ARNs.

---

## 15) Versioning & compatibility

- Toolset semver: bump minor for backward-compatible additions, major for breaking changes.
- Manifest:
  - Include `toolset_version` and `manifest_version` timestamps in `describe_tools`.
  - MCP stubs cache invalidation on version change.
- MCP server stubs package (PyPI):
  - Semver and changelog; aim for backward compatibility with older manifests.

---

## 16) Deployment strategy (no canary)

- AllAtOnce alias update per env.
- Rollback:
  - On failure, CloudFormation auto-rollback.
  - Manual rollback by re-pointing alias to previous version.
- Freeze windows:
  - Optional for prod; approvals can be added in CodePipeline.

---

## 17) Operational runbooks

- **Add a tool to an existing toolset**
  - Implement `@tool` + Pydantic models.
  - Ensure it’s included in `describe_tools`.
  - Commit → pipeline runs → deploy → registry updated → MCP refresh picks it up.

- **Add a new toolset**
  - Scaffold `toolsets/<name>/` with code/tests/`toolset.yaml`.
  - Commit → synth creates new stacks → deploy to env → registry entry appears.
  - Grant MCP role invoke rights (handled by CDK if central policy includes pattern).

- **Breaking change**
  - Bump major; deploy dev → validate → promote to test → prod.

- **Rotate secret**
  - Update secret in Secrets Manager; no code change required.
  - Redeploy only if environment variables changed.

---

## 18) Open questions and assumptions

- Assume separate AWS accounts per env (preferred). If single account, ensure strict resource naming and IAM conditions by alias.
- Artifact storage: S3 bucket per account for CDK templates and Lambda zips.
- Dependency strategy: prefer Lambda Layer for shared runtime; keep function zips small.
- MCP reload strategy: server restart or periodic registry refresh (e.g., every 5 minutes).

---

## 19) Future enhancements

- Canary/linear deployments via CodeDeploy aliases (when desired).
- AppConfig for faster, cacheable registry reads and dynamic feature flags.
- Blue/green shadow testing via dual-invoke and result comparison.
- Cost controls: Provisioned Concurrency for critical low-latency toolsets; auto-scale only where needed.
- Plugin discovery (Pluggy) for third-party toolsets if needed later.

---

## 20) Acceptance criteria checklist

- Toolsets deploy per env with Lambda + alias.
- `describe_tools` and `invoke` RPCs live and validated.
- MCP server stubs package loads registry, generates stubs, and invokes successfully.
- CodePipeline runs tests, synths, and deploys changed toolsets.
- SSM registry entries are present and correct per env.
- IAM isolation: dev MCP can invoke only `:dev` aliases, etc.
- CloudFormation Hooks block invalid configs.
- Observability metrics and alarms active.

---

### Appendix A: Example IAM for MCP dev role
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeDevToolsets",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:us-west-2:123456789012:function:toolset-*-*:dev"
    },
    {
      "Sid": "ReadDevRegistry",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:GetParametersByPath"],
      "Resource": "arn:aws:ssm:us-west-2:123456789012:parameter/toolforest/dev/toolsets/*"
    }
  ]
}
```

### Appendix B: Example registry reader usage (server stubs package)
```python
from mcp_remote_toolsets import load_registry, load_toolset_proxies

env = "dev"
entries = load_registry(env)  # reads SSM, returns list of toolset descriptors
proxies = load_toolset_proxies(entries)  # builds callable stubs with proper signatures
# register proxies with FastMCP app
```

### Appendix C: Minimal CloudFormation Hook checks
- Validate runtime ∈ {python3.12}
- Alias name equals env
- Timeout ≤ 30s; memory ≤ 1024 MB (policy)
- Required tags: `toolset_id`, `env`, `owner`
- Disallow public function URLs (if policy requires)
