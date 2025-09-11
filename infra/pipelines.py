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

        test_project = codebuild.PipelineProject(
            self,
            "TestProject",
            environment=codebuild.BuildEnvironment(build_image=codebuild.LinuxBuildImage.STANDARD_7_0, privileged=True),
            environment_variables={"ENV": codebuild.BuildEnvironmentVariable(value=env_name)},
            build_spec=codebuild.BuildSpec.from_source_filename("pipeline/buildspecs/test.yml"),
            cache=codebuild.Cache.bucket(cache_bucket, prefix=f"toolforest/tools/test/{env_name}"),
        )

        build_project = codebuild.PipelineProject(
            self,
            "BuildProject",
            environment=codebuild.BuildEnvironment(build_image=codebuild.LinuxBuildImage.STANDARD_7_0, privileged=True),
            environment_variables={"ENV": codebuild.BuildEnvironmentVariable(value=env_name)},
            build_spec=codebuild.BuildSpec.from_source_filename("pipeline/buildspecs/build.yml"),
            cache=codebuild.Cache.bucket(cache_bucket, prefix=f"toolforest/tools/build/{env_name}"),
        )

        # Inline deploy buildspec so it does not depend on primary source containing the file
        deploy_buildspec = codebuild.BuildSpec.from_object(
            {
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {"python": "3.12"},
                        "commands": [
                            "curl -LsSf https://astral.sh/uv/install.sh | sh",
                            "export PATH=$HOME/.local/bin:$PATH",
                            "uv venv --python 3.12",
                            ". .venv/bin/activate",
                            "uv pip install -r requirements.txt",
                            "npm install -g aws-cdk@2",
                        ],
                    },
                    "build": {
                        "commands": [
                            "echo Ensure cdk.out available from artifacts",
                            "if [ ! -d cdk.out ]; then CANDIDATE=$(find . -maxdepth 3 -type d -name cdk.out | head -n1 || true); if [ -n \"$CANDIDATE\" ]; then echo Using cdk.out from $CANDIDATE; cp -R \"$CANDIDATE\" ./cdk.out; else echo cdk.out not found; exit 1; fi; fi",
                            "echo Deploy from pre-synthesized templates",
                            "ENV=$ENV OWNER=${OWNER:-pipeline@toolforest.io} npx cdk deploy --app cdk.out --require-approval never",
                            "echo Smoke test for $ENV",
                            # Locate smoke script in secondary source (repo) and run it
                            "SMOKE=$(find . -maxdepth 5 -type f -path '*/scripts/smoke_invoke.py' | head -n1 || true)",
                            "if [ -z \"$SMOKE\" ]; then echo 'smoke_invoke.py not found'; exit 1; fi",
                            ". .venv/bin/activate && PYTHONPATH=packages/mcp-remote-toolsets/src ENV=$ENV python3 \"$SMOKE\"",
                        ],
                    },
                },
                "artifacts": {"files": ["cdk.out/**"]},
            }
        )

        deploy_project = codebuild.PipelineProject(
            self,
            "DeployProject",
            environment=codebuild.BuildEnvironment(build_image=codebuild.LinuxBuildImage.STANDARD_7_0, privileged=True),
            environment_variables={
                "ENV": codebuild.BuildEnvironmentVariable(value=env_name),
                "OWNER": codebuild.BuildEnvironmentVariable(value=os.getenv("OWNER", "gerrit@toolforest.io")),
            },
            build_spec=deploy_buildspec,
            cache=codebuild.Cache.bucket(cache_bucket, prefix=f"toolforest/tools/deploy/{env_name}"),
        )

        if deploy_project.role:
            deploy_project.role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AdministratorAccess"))

        test_action = cpactions.CodeBuildAction(action_name="Test", project=test_project, input=source_output)
        build_action = cpactions.CodeBuildAction(action_name="Build", project=build_project, input=source_output, outputs=[build_output])
        # Provide both artifacts: primary is SynthOutput, extra is source repo for smoke script
        deploy_action = cpactions.CodeBuildAction(action_name="DeployAndValidate", project=deploy_project, input=build_output, extra_inputs=[source_output])

        pipeline = codepipeline.Pipeline(self, "Pipeline", pipeline_name=f"toolforest-tools-pipeline-{env_name}", pipeline_type=codepipeline.PipelineType.V2)

        pipeline.add_stage(stage_name="Source", actions=[source_action])
        pipeline.add_stage(stage_name="Test", actions=[test_action])
        pipeline.add_stage(stage_name="Build", actions=[build_action])

        if env_name == "prod":
            approval = cpactions.ManualApprovalAction(action_name="ManualApproval")
            pipeline.add_stage(stage_name="Approve", actions=[approval])

        pipeline.add_stage(stage_name="Deploy", actions=[deploy_action])


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
