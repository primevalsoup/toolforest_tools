from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_cloudwatch as cw,
    aws_ssm as ssm,
)
from constructs import Construct


class ToolsetStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, toolset_dir: Path, env_name: str, default_tags: Dict[str, str]) -> None:
        super().__init__(scope, construct_id)

        with open(toolset_dir / "toolset.yaml", "r", encoding="utf-8") as f:
            import yaml

            cfg = yaml.safe_load(f)

        name = cfg["name"]
        function_name = f"toolforest-tool-{name}-{env_name}"
        runtime = cfg.get("runtime", "python3.12")
        handler = cfg.get("handler", "lambda_handler.handler")
        memory = int(cfg.get("memory_mb", 256))
        timeout = int(cfg.get("timeout_s", 15))
        env_vars = cfg.get("env", {})
        layers_arn = cfg.get("layers", [])
        permissions = cfg.get("permissions", [])
        alarms = cfg.get("alarms", {})
        toolset_id = cfg.get("toolset_id")

        # Tags
        cdk.Tags.of(self).add("toolset_id", toolset_id)
        for k, v in default_tags.items():
            cdk.Tags.of(self).add(k, v)
        # Mark stacks for our CFN Hook to enforce policies only on tagged stacks
        cdk.Tags.of(self).add("toolforest-tools", "1")

        # Role
        role = iam.Role(
            self,
            "ExecRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
        )
        for action in permissions:
            role.add_to_policy(iam.PolicyStatement(actions=[action], resources=["*"]))

        # Layers
        layer_objs = [
            _lambda.LayerVersion.from_layer_version_arn(self, f"Layer{i}", arn)
            for i, arn in enumerate(layers_arn)
        ]

        # Bundle function code with runtime and minimal deps
        bundle_cmd = (
            f"set -euo pipefail; "
            f"mkdir -p /asset-output; "
            f"cp -r /asset-input/toolsets/{name}/src/* /asset-output/; "
            f"mkdir -p /asset-output/mcp_lambda_runtime; "
            f"cp -r /asset-input/packages/mcp-lambda-runtime/src/mcp_lambda_runtime/* /asset-output/mcp_lambda_runtime/; "
            f"pip install --no-cache-dir -t /asset-output pydantic==2.8.2"
        )

        fn = _lambda.Function(
            self,
            "Function",
            function_name=function_name,
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler=handler,
            code=_lambda.Code.from_asset(
                path=".",
                bundling=cdk.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=["bash", "-lc", bundle_cmd],
                ),
            ),
            role=role,
            memory_size=memory,
            timeout=cdk.Duration.seconds(timeout),
            environment={"ENV": env_name, **env_vars},
            layers=layer_objs,
            architecture=_lambda.Architecture.ARM_64,
        )

        version = fn.current_version
        alias = _lambda.Alias(self, "Alias", alias_name=env_name, version=version)
        alias_arn = cdk.Fn.sub("${FnArn}:${Alias}", {"FnArn": fn.function_arn, "Alias": env_name})

        # Alarms
        if alarms:
            if "errors_threshold" in alarms:
                metric_errors = alias.metric_errors(period=cdk.Duration.minutes(1))
                cw.Alarm(
                    self,
                    "ErrorsAlarm",
                    metric=metric_errors,
                    threshold=float(alarms["errors_threshold"]),
                    evaluation_periods=1,
                )
            if "duration_p95_ms" in alarms:
                base_metric = alias.metric_duration(period=cdk.Duration.minutes(1))
                p95_metric = base_metric.with_(statistic="p95")
                cw.Alarm(
                    self,
                    "DurationAlarm",
                    metric=p95_metric,
                    threshold=float(alarms["duration_p95_ms"]),
                    evaluation_periods=1,
                )

        # Registry write to SSM as a JSON string
        registry_str = cdk.Fn.sub(
            '{"toolset_id":"${ToolsetId}","name":"${Name}","lambda_function_arn":"${FnArn}","alias":"${Env}","alias_arn":"${AliasArn}","version":"${Version}","manifest_version":""}',
            {
                "ToolsetId": toolset_id,
                "Name": name,
                "FnArn": fn.function_arn,
                "Env": env_name,
                "AliasArn": alias_arn,
                "Version": version.version,
            },
        )
        ssm.StringParameter(
            self,
            "RegistryEntry",
            parameter_name=f"/toolforest/{env_name}/toolsets/{name}",
            string_value=registry_str,
        )


def build_toolset_stacks(*, app: cdk.App, env_name: str, default_tags: Dict[str, str]) -> None:
    toolsets_root = Path("toolsets")
    for toolset_dir in toolsets_root.iterdir():
        if not (toolset_dir / "toolset.yaml").exists():
            continue
        name = toolset_dir.name
        ToolsetStack(
            app,
            f"Toolset-{name}-{env_name}",
            toolset_dir=toolset_dir,
            env_name=env_name,
            default_tags=default_tags,
        )
