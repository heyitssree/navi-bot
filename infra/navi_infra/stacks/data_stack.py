"""Data: the private S3 bucket holding Litestream replicas, the seed databases, media and exports."""
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, aws_s3 as s3, aws_ssm as ssm
from constructs import Construct

from navi_infra.config import NaviConfig


class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: NaviConfig, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.bucket = s3.Bucket(
            self, "BotData",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=False,                      # Litestream manages its own generations
            removal_policy=RemovalPolicy.RETAIN,  # never lose bot data when a stack is deleted
            lifecycle_rules=[
                s3.LifecycleRule(id="exports-30d", prefix="exports/", expiration=Duration.days(30)),
                s3.LifecycleRule(id="abort-mpu", abort_incomplete_multipart_upload_after=Duration.days(1)),
            ],
        )
        # The scripts (seed-db.sh) read the bucket name from here instead of needing CloudFormation access.
        ssm.StringParameter(
            self, "BucketName", parameter_name=f"{cfg.ssm_prefix}/bucket", string_value=self.bucket.bucket_name)
        CfnOutput(self, "BucketNameOutput", value=self.bucket.bucket_name)
