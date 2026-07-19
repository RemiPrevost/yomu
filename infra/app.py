#!/usr/bin/env python3
"""CDK app for the Language Memory service (personal account, eu-west-1)."""

import aws_cdk as cdk

from stacks.language_memory_stack import LanguageMemoryStack

app = cdk.App()
LanguageMemoryStack(
    app,
    "LanguageMemory",
    env=cdk.Environment(region="eu-west-1"),
)
app.synth()
