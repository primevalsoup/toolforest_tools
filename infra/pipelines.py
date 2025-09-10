from __future__ import annotations

import os
from typing import Optional

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_codebuild as codebuild,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as cpactions,
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
        github_token_param: str | None,
    ) -> None:
        super().__init__(scope, construct_id)

        source_output = codepipeline.Artifact()

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
            if not github_token_param:
                raise ValueError("GitHub token SSM parameter path must be provided when no CodeStar connection ARN is set")
            source_action = cpactions.GitHubSourceAction(
                action_name="Source",
                owner=github_owner,
                repo=github_repo,
                branch=github_branch,
                oauth_token=cdk.SecretValue.ssm_secure(github_token_param, version='1'),
                output=source_output,
                trigger=cpactions.GitHubTrigger.WEBHOOK,
            )

        project = codebuild.PipelineProject(
            self,
            "DeployProject",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,
            ),
            environment_variables={
                "ENV": codebuild.BuildEnvironmentVariable(value=env_name),
                "OWNER": codebuild.BuildEnvironmentVariable(value=os.getenv("OWNER", "gerrit@toolforest.io")),
            },
            build_spec=codebuild.BuildSpec.from_source_filename("pipeline/buildspecs/synth_deploy.yml"),
        )

        deploy_action = cpactions.CodeBuildAction(
            action_name="SynthAndDeploy",
            project=project,
            input=source_output,
        )

        pipeline = codepipeline.Pipeline(self, "Pipeline")
        pipeline.add_stage(stage_name="Source", actions=[source_action])
        pipeline.add_stage(stage_name="Deploy", actions=[deploy_action])


def build_pipelines(app: cdk.App) -> None:
    connection_arn = app.node.try_get_context("github_connection_arn") or os.getenv("GITHUB_CONNECTION_ARN")
    github_owner = app.node.try_get_context("github_owner") or os.getenv("GITHUB_OWNER")
    github_repo = app.node.try_get_context("github_repo") or os.getenv("GITHUB_REPO")
    github_token_param = app.node.try_get_context("github_token_param") or os.getenv("GITHUB_TOKEN_PARAM") or "/toolforest/github/token"

    if not (github_owner and github_repo):
        # Skip creating pipelines if repo info is missing
        return

    # Branch-to-env mapping
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
            github_token_param=None if connection_arn else github_token_param,
        )
