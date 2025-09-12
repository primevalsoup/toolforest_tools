from __future__ import annotations

import os
from typing import Optional

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_codebuild as codebuild,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as cpactions,
    aws_iam as iam,
    aws_s3 as s3,
)
from constructs import Construct


class ToolsetPipelineStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        github_owner: str,
        github_repo: str,
        github_branch: str,
        connection_arn: str | None,
        github_token_secret_name: str | None,
    ) -> None:
        super().__init__(scope, construct_id)

        cache_bucket = s3.Bucket(
            self,
            "CodeBuildCacheBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=False,
            auto_delete_objects=False,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        source_output = codepipeline.Artifact()
        build_output = codepipeline.Artifact(artifact_name="SynthOutput")

        if connection_arn:
            source_action = cpactions.CodeStarConnectionsSourceAction(
                action_name="Source",
                owner=github_owner,
                repo=github_repo,
                branch=github_branch,
                connection_arn=connection_arn,
                output=source_output,
                trigger_on_push=True,
            )
        else:
            if not github_token_secret_name:
                raise ValueError("GitHub token Secrets Manager secret name must be provided when no CodeStar connection ARN is set")
            source_action = cpactions.GitHubSourceAction(
                action_name="Source",
                owner=github_owner,
                repo=github_repo,
                branch=github_branch,
                oauth_token=cdk.SecretValue.secrets_manager(github_token_secret_name),
                output=source_output,
                trigger=cpactions.GitHubTrigger.WEBHOOK,
            )

        # Compute type: SMALL for all environments
        compute_type = codebuild.ComputeType.SMALL

        # Inline Test buildspec
        test_buildspec = codebuild.BuildSpec.from_object(
            {
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {"python": "3.12"},
                        "commands": [
                            "python3 -m venv .venv",
                            ". .venv/bin/activate",
                            "python -m pip install --upgrade pip",
                            "REQ=\"\"; if [ -f requirements.txt ]; then REQ=requirements.txt; else for d in $(env | awk -F= '/^CODEBUILD_SRC_DIR/ {print $2}'); do if [ -f \"$d/requirements.txt\" ]; then REQ=\"$d/requirements.txt\"; break; fi; done; fi; if [ -z \"$REQ\" ]; then REQ=$(find . -maxdepth 4 -type f -name requirements.txt | head -n1 || true); fi; if [ -z \"$REQ\" ]; then echo 'requirements.txt not found'; exit 1; fi; echo Using requirements at $REQ",
                            "pip install -r \"$REQ\"",
                            # Install client adapter from GitHub using token
                            "if [ -n \"$GITHUB_PAT\" ]; then pip install git+https://$GITHUB_PAT@github.com/primevalsoup/toolforest_tools_client.git@v0.1.0#egg=mcp-server-adapter; else echo GITHUB_PAT not set; fi",
                        ],
                    },
                    "build": {"commands": [". .venv/bin/activate && pytest -q toolsets"]},
                },
            }
        )

        test_project = codebuild.PipelineProject(
            self,
            "TestProject",
            project_name=f"toolforest-tools-test-{env_name}",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,
                compute_type=compute_type,
            ),
            environment_variables={
                "ENV": codebuild.BuildEnvironmentVariable(value=env_name),
                "CB_CUSTOM_CACHE_DIR": codebuild.BuildEnvironmentVariable(value=".venv/.cache/pip"),
                # Provide GitHub token to build for private repo install
                "GITHUB_PAT": codebuild.BuildEnvironmentVariable(
                    value=github_token_secret_name or "",
                    type=codebuild.BuildEnvironmentVariableType.SECRETS_MANAGER,
                ),
            },
            build_spec=test_buildspec,
            cache=codebuild.Cache.local(codebuild.LocalCacheMode.CUSTOM),
        )

        # Inline Build buildspec
        build_buildspec = codebuild.BuildSpec.from_object(
            {
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {"python": "3.12"},
                        "commands": [
                            "python3 -m venv .venv",
                            ". .venv/bin/activate",
                            "python -m pip install --upgrade pip",
                            "REQ=\"\"; if [ -f requirements.txt ]; then REQ=requirements.txt; else for d in $(env | awk -F= '/^CODEBUILD_SRC_DIR/ {print $2}'); do if [ -f \"$d/requirements.txt\" ]; then REQ=\"$d/requirements.txt\"; break; fi; done; fi; if [ -z \"$REQ\" ]; then REQ=$(find . -maxdepth 4 -type f -name requirements.txt | head -n1 || true); fi; if [ -z \"$REQ\" ]; then echo 'requirements.txt not found'; exit 1; fi; echo Using requirements at $REQ",
                            "pip install -r \"$REQ\"",
                            # Install client adapter for synth-time references if needed
                            "if [ -n \"$GITHUB_PAT\" ]; then pip install git+https://$GITHUB_PAT@github.com/primevalsoup/toolforest_tools_client.git@v0.1.0#egg=mcp-server-adapter; else echo GITHUB_PAT not set; fi",
                            "npm install -g aws-cdk@2",
                        ],
                    },
                    "build": {"commands": ["ENV=$ENV npx cdk synth"]},
                },
                "artifacts": {"files": ["cdk.out/**"]},
            }
        )

        build_project = codebuild.PipelineProject(
            self,
            "BuildProject",
            project_name=f"toolforest-tools-build-{env_name}",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,
                compute_type=compute_type,
            ),
            environment_variables={
                "ENV": codebuild.BuildEnvironmentVariable(value=env_name),
                "CB_CUSTOM_CACHE_DIR": codebuild.BuildEnvironmentVariable(value=".venv/.cache/pip"),
                "GITHUB_PAT": codebuild.BuildEnvironmentVariable(
                    value=github_token_secret_name or "",
                    type=codebuild.BuildEnvironmentVariableType.SECRETS_MANAGER,
                ),
            },
            build_spec=build_buildspec,
            cache=codebuild.Cache.local(codebuild.LocalCacheMode.DOCKER_LAYER, codebuild.LocalCacheMode.CUSTOM),
        )

        # Inline deploy buildspec so it does not depend on primary source containing the file
        deploy_buildspec = codebuild.BuildSpec.from_object(
            {
                "version": "0.2",
                "env": {"variables": {"CB_CUSTOM_CACHE_DIR": ".venv/.cache/pip"}},
                "phases": {
                    "install": {
                        "runtime-versions": {"python": "3.12"},
                        "commands": [
                            # Create venv with system Python and install requirements from source artifact
                            "python3 -m venv .venv",
                            ". .venv/bin/activate",
                            "python -m pip install --upgrade pip",
                            # Resolve requirements.txt from any input artifact
                            "REQ=\"\"; if [ -f requirements.txt ]; then REQ=requirements.txt; else for d in $(env | awk -F= '/^CODEBUILD_SRC_DIR_/ {print $2}'); do if [ -f \"$d/requirements.txt\" ]; then REQ=\"$d/requirements.txt\"; break; fi; done; fi; if [ -z \"$REQ\" ]; then REQ=$(find .. -maxdepth 4 -type f -name requirements.txt | head -n1 || true); fi; if [ -z \"$REQ\" ]; then echo 'requirements.txt not found in inputs'; exit 1; fi; echo Using requirements at $REQ",
                            "pip install -r \"$REQ\"",
                            # Install client adapter for deploy-time smoke
                            "if [ -n \"$GITHUB_PAT\" ]; then pip install git+https://$GITHUB_PAT@github.com/primevalsoup/toolforest_tools_client.git@v0.1.0#egg=mcp-server-adapter; else echo GITHUB_PAT not set; fi",
                            "npm install -g aws-cdk@2",
                        ],
                    },
                    "build": {
                        "commands": [
                            # Locate smoke script within input artifacts and derive repo root
                            "SMOKE=\"\"; for d in $(env | awk -F= '/^CODEBUILD_SRC_DIR_/ {print $2}'); do CAND=$(find \"$d\" -maxdepth 6 -type f -path '*/scripts/smoke_invoke.py' | head -n1 || true); if [ -n \"$CAND\" ]; then SMOKE=\"$CAND\"; break; fi; done; if [ -z \"$SMOKE\" ]; then echo 'smoke_invoke.py not found in inputs'; exit 1; fi; echo Using smoke at $SMOKE",
                            "REPO_ROOT=$(dirname \"$(dirname \"$SMOKE\")\")",
                            "echo Deploy from source using CDK app",
                            "(cd \"$REPO_ROOT\" && ENV=$ENV OWNER=${OWNER:-pipeline@toolforest.io} npx cdk deploy --require-approval never)",
                            "echo Smoke test for $ENV",
                            ". .venv/bin/activate && PYTHONPATH=\"$REPO_ROOT/packages/mcp-remote-toolsets/src\" ENV=$ENV python3 \"$SMOKE\"",
                        ],
                    },
                },
                "artifacts": {"files": ["cdk.out/**"]},
            }
        )

        deploy_project = codebuild.PipelineProject(
            self,
            "DeployProject",
            project_name=f"toolforest-tools-deploy-{env_name}",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,
                compute_type=compute_type,
            ),
            environment_variables={
                "ENV": codebuild.BuildEnvironmentVariable(value=env_name),
                "OWNER": codebuild.BuildEnvironmentVariable(value=os.getenv("OWNER", "gerrit@toolforest.io")),
                "CB_CUSTOM_CACHE_DIR": codebuild.BuildEnvironmentVariable(value=".venv/.cache/pip"),
                "GITHUB_PAT": codebuild.BuildEnvironmentVariable(
                    value=github_token_secret_name or "",
                    type=codebuild.BuildEnvironmentVariableType.SECRETS_MANAGER,
                ),
            },
            build_spec=deploy_buildspec,
            cache=codebuild.Cache.local(codebuild.LocalCacheMode.DOCKER_LAYER, codebuild.LocalCacheMode.CUSTOM),
        )

        if deploy_project.role:
            deploy_project.role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AdministratorAccess"))

        test_action = cpactions.CodeBuildAction(action_name=f"toolforest-tools-test-{env_name}", project=test_project, input=source_output)
        build_action = cpactions.CodeBuildAction(action_name=f"toolforest-tools-build-{env_name}", project=build_project, input=source_output, outputs=[build_output])
        # Provide both artifacts: primary is SynthOutput, extra is source repo for smoke script
        deploy_action = cpactions.CodeBuildAction(action_name=f"toolforest-tools-deploy-{env_name}", project=deploy_project, input=build_output, extra_inputs=[source_output])

        pipeline = codepipeline.Pipeline(self, "Pipeline", pipeline_name=f"toolforest-tools-pipeline-{env_name}", pipeline_type=codepipeline.PipelineType.V2)

        pipeline.add_stage(stage_name=f"toolforest-tools-source-{env_name}", actions=[source_action])
        pipeline.add_stage(stage_name=f"toolforest-tools-test-{env_name}", actions=[test_action])
        pipeline.add_stage(stage_name=f"toolforest-tools-build-{env_name}", actions=[build_action])

        if env_name == "prod":
            approval = cpactions.ManualApprovalAction(action_name=f"toolforest-tools-approve-{env_name}")
            pipeline.add_stage(stage_name=f"toolforest-tools-approve-{env_name}", actions=[approval])

        pipeline.add_stage(stage_name=f"toolforest-tools-deploy-{env_name}", actions=[deploy_action])


def build_pipelines(app: cdk.App) -> None:
    connection_arn = app.node.try_get_context("github_connection_arn") or os.getenv("GITHUB_CONNECTION_ARN")
    github_owner = app.node.try_get_context("github_owner") or os.getenv("GITHUB_OWNER")
    github_repo = app.node.try_get_context("github_repo") or os.getenv("GITHUB_REPO")
    github_token_secret_name = app.node.try_get_context("github_token_secret_name") or os.getenv("GITHUB_TOKEN_SECRET_NAME")

    if not (github_owner and github_repo):
        return

    mappings = {
        "develop": "dev",
        "test": "test",
        "main": "prod",
    }

    for branch, env_name in mappings.items():
        ToolsetPipelineStack(
            app,
            f"Toolforest-Toolsets-Pipeline-{env_name}",
            env_name=env_name,
            github_owner=github_owner,
            github_repo=github_repo,
            github_branch=branch,
            connection_arn=connection_arn,
            github_token_secret_name=None if connection_arn else github_token_secret_name,
        )
