"""Single stack: DynamoDB table + 2 GSIs, Lambda (MCP server), Function URL.

The bearer token lives in an SSM SecureString created once by hand (CDK cannot
create SecureStrings):

    aws ssm put-parameter --region eu-west-1 --name /yomu/auth-token \
        --type SecureString --value "$(openssl rand -hex 32)"

The Lambda asset is built by scripts/build_lambda.sh (run it before deploy).
"""

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

AUTH_TOKEN_PARAM = "/yomu/auth-token"


class LanguageMemoryStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.Table(
            self,
            "Table",
            table_name="language-memory",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        table.add_global_secondary_index(
            index_name="GSI1-queue",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="queue_key", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.INCLUDE,
            non_key_attributes=[
                "state",
                "facet",
                "due",
                "reps",
                "lapses",
                "last_review",
                "first_review",
            ],
        )
        table.add_global_secondary_index(
            index_name="GSI2-dedup",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="normalized", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.INCLUDE,
            non_key_attributes=["lemma", "pos", "meanings", "concept_id"],
        )

        function = lambda_.Function(
            self,
            "McpServer",
            function_name="language-memory-mcp",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="yomu.lambda_handler.handler",
            code=lambda_.Code.from_asset("../dist/lambda"),
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            environment={
                "TABLE_NAME": table.table_name,
                "AUTH_TOKEN_PARAM": AUTH_TOKEN_PARAM,
                "USER_ID": "u_001",
            },
        )
        table.grant_read_write_data(function)
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    self.format_arn(
                        service="ssm",
                        resource="parameter",
                        resource_name=AUTH_TOKEN_PARAM.lstrip("/"),
                    )
                ],
            )
        )

        url = function.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

        cdk.CfnOutput(self, "TableName", value=table.table_name)
        cdk.CfnOutput(self, "McpEndpoint", value=f"{url.url}mcp")
