from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
)
from constructs import Construct


class HooksStack(Stack):
    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        validator = _lambda.Function(
            self,
            "HookValidator",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("hooks/validator/src"),
            function_name="toolforest-cfn-hook-validator",
            description="Validates toolforest toolset stacks; no-ops unless stack tag toolforest-tools=1",
        )

        cdk.CfnOutput(self, "ValidatorArn", value=validator.function_arn)
