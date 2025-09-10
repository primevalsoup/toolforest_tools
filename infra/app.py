#!/usr/bin/env python3
from __future__ import annotations

import os

import aws_cdk as cdk

from infra.toolset_stacks import build_toolset_stacks
from infra.pipelines import build_pipelines


app = cdk.App()

env_name = os.getenv("ENV", "dev")
owner = os.getenv("OWNER", "gerrit@toolforest.io")
region = os.getenv("CDK_DEFAULT_REGION", "us-west-2")
account = os.getenv("CDK_DEFAULT_ACCOUNT")

build_toolset_stacks(app=app, env_name=env_name, default_tags={"owner": owner, "env": env_name})

# Optionally synth pipelines if connection/repo info is set
build_pipelines(app)

app.synth()
