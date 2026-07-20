"""Single stack: DynamoDB table + 2 GSIs, Lambda (MCP server), Function URL.

The bearer token lives in an SSM SecureString created once by hand (CDK cannot
create SecureStrings):

    aws ssm put-parameter --region eu-west-1 --name /yomu/auth-token \
        --type SecureString --value "$(openssl rand -hex 32)"

The Lambda asset is built by scripts/build_lambda.sh (run it before deploy).
"""

import aws_cdk as cdk
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

AUTH_TOKEN_PARAM = "/yomu/auth-token"
# The Function URL is stable once created, but referencing it from the
# function's own environment would be a circular CFN dependency — so the
# public URL is pinned here after the first deploy.
MCP_PUBLIC_URL = "https://i4khzawjpjrlaaxbfj73buxd7i0upzfk.lambda-url.eu-west-1.on.aws/mcp"

# OAuth redirect URIs of the MCP clients we use. Cognito requires an exact
# match; http is only allowed for localhost (dev tooling).
OAUTH_CALLBACKS = [
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
    "http://localhost:6274/oauth/callback",  # MCP Inspector
    "http://localhost:3334/oauth/callback",  # mcp-remote (Claude Desktop bridge)
]


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

        # ---- Auth phase 2: Cognito user pool as OAuth 2.1 authorization server.
        # No self-signup: users are created by hand (personal project). The MCP
        # client (claude.ai) is a public client using code + PKCE; the client ID
        # is entered manually in claude.ai's connector "Advanced settings".
        user_pool = cognito.UserPool(
            self,
            "Users",
            user_pool_name="yomu-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        domain = user_pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"yomu-{self.account}"),
        )
        client = user_pool.add_client(
            "McpClient",
            user_pool_client_name="mcp-clients",
            generate_secret=False,
            prevent_user_existence_errors=True,
            auth_flows=cognito.AuthFlow(user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=OAUTH_CALLBACKS,
            ),
            access_token_validity=cdk.Duration.hours(1),
            refresh_token_validity=cdk.Duration.days(90),
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
                "COGNITO_ISSUER": user_pool.user_pool_provider_url,
                "COGNITO_CLIENT_ID": client.user_pool_client_id,
                "COGNITO_HOSTED_DOMAIN": domain.base_url(),
                "MCP_PUBLIC_URL": MCP_PUBLIC_URL,
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
        cdk.CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        cdk.CfnOutput(self, "OAuthClientId", value=client.user_pool_client_id)
        cdk.CfnOutput(self, "CognitoIssuer", value=user_pool.user_pool_provider_url)
        cdk.CfnOutput(self, "HostedUiDomain", value=domain.base_url())
