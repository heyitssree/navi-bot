"""Compute: one Graviton instance in an Auto Scaling group of exactly one (self-healing, never two bots at once)."""
from pathlib import Path

from aws_cdk import (
    Duration, RemovalPolicy, Stack, aws_autoscaling as autoscaling, aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets, aws_iam as iam, aws_logs as logs, aws_ssm as ssm,
)
from constructs import Construct

from navi_infra.config import NaviConfig
from navi_infra.userdata import render_user_data

REPO_ROOT = Path(__file__).resolve().parents[3]

IMAGE_EXCLUDES = [
    "infra", ".git", ".venv", "data", "logs", "reports", "docs", "tests", "tools", ".env*", "*.db", "*.md",
    "**/__pycache__", ".pytest_cache", ".ruff_cache",
]


class ComputeStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: NaviConfig, vpc: ec2.IVpc, bucket, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        image = ecr_assets.DockerImageAsset(
            self, "BotImage", directory=str(REPO_ROOT), platform=ecr_assets.Platform.LINUX_ARM64,
            exclude=IMAGE_EXCLUDES)

        image_param = ssm.StringParameter(
            self, "ImageUri", parameter_name=f"{cfg.ssm_prefix}/image_uri", string_value=image.image_uri)

        log_group = logs.LogGroup(
            self, "BotLogs", log_group_name=f"{cfg.ssm_prefix}/bot",
            retention=logs.RetentionDays.TWO_WEEKS, removal_policy=RemovalPolicy.DESTROY)

        sg = ec2.SecurityGroup(self, "BotSg", vpc=vpc, allow_all_outbound=True, description="Navi bot - no inbound rules")

        role = iam.Role(
            self, "BotRole", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")])  # Session Manager, no SSH
        bucket.grant_read_write(role)                    # Litestream replicas, seed databases, media, exports
        image.repository.grant_pull(role)
        log_group.grant_write(role)
        image_param.grant_read(role)
        role.add_to_policy(iam.PolicyStatement(
            sid="ReadNaviParameters",
            actions=["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
            resources=[self.format_arn(service="ssm", resource="parameter", resource_name=f"navi/{cfg.env_name}/*")]))
        role.add_to_policy(iam.PolicyStatement(
            sid="DecryptParametersViaSsm", actions=["kms:Decrypt"], resources=["*"],
            conditions={"StringEquals": {"kms:ViaService": f"ssm.{self.region}.amazonaws.com"}}))

        # Bedrock. A plain on-demand model (e.g. Gemma) needs one statement. A global cross-Region profile needs three
        # (profile in this region, the in-region foundation model, the global foundation-model resource), tied to the profile ARN.
        invoke = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        if cfg.bedrock_uses_profile:
            profile_arn = self.format_arn(service="bedrock", resource="inference-profile", resource_name=cfg.bedrock_profile_id)
            role.add_to_policy(iam.PolicyStatement(sid="BedrockProfileInRegion", actions=invoke, resources=[profile_arn]))
            role.add_to_policy(iam.PolicyStatement(
                sid="BedrockModelInRegion", actions=invoke,
                resources=[f"arn:aws:bedrock:{self.region}::foundation-model/{cfg.bedrock_model_arn_pattern}"],
                conditions={"StringEquals": {"bedrock:InferenceProfileArn": profile_arn}}))
            role.add_to_policy(iam.PolicyStatement(
                sid="BedrockModelGlobal", actions=invoke,
                resources=[f"arn:aws:bedrock:::foundation-model/{cfg.bedrock_model_arn_pattern}"],
                conditions={"StringEquals": {"aws:RequestedRegion": "unspecified", "bedrock:InferenceProfileArn": profile_arn}}))
            role.add_to_policy(iam.PolicyStatement(sid="BedrockStartupCheck", actions=["bedrock:GetInferenceProfile"], resources=[profile_arn]))
        else:
            role.add_to_policy(iam.PolicyStatement(
                sid="BedrockModelOnDemand", actions=invoke,
                resources=[f"arn:aws:bedrock:{self.region}::foundation-model/{cfg.bedrock_model_arn_pattern}"]))
        role.add_to_policy(iam.PolicyStatement(
            sid="Heartbeat", actions=["cloudwatch:PutMetricData"], resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": "Navi"}}))

        user_data = ec2.UserData.for_linux()
        user_data.add_commands(*render_user_data(
            env_name=cfg.env_name, region=self.region, bucket=bucket.bucket_name, log_group=log_group.log_group_name,
            image_param=image_param.parameter_name, bedrock_model_id=cfg.bedrock_profile_id))

        launch_template = ec2.LaunchTemplate(
            self, "BotLt",
            instance_type=ec2.InstanceType(cfg.instance_type),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(cpu_type=ec2.AmazonLinuxCpuType.ARM_64),
            role=role, security_group=sg, user_data=user_data,
            associate_public_ip_address=True,
            require_imdsv2=True,
            http_put_response_hop_limit=2,       # REQUIRED: lets the container reach the instance-role credentials
            block_devices=[ec2.BlockDevice(
                device_name="/dev/xvda",
                volume=ec2.BlockDeviceVolume.ebs(
                    cfg.root_volume_gib, volume_type=ec2.EbsDeviceVolumeType.GP3, encrypted=True,
                    delete_on_termination=True))],
            spot_options=(ec2.LaunchTemplateSpotOptions(interruption_behavior=ec2.SpotInstanceInterruption.TERMINATE)
                          if cfg.use_spot else None))

        self.asg = autoscaling.AutoScalingGroup(
            self, "BotAsg", vpc=vpc, vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            launch_template=launch_template, min_capacity=1, max_capacity=1,
            # never two bots at once: the old instance is terminated before its replacement starts
            update_policy=autoscaling.UpdatePolicy.rolling_update(min_instances_in_service=0, max_batch_size=1,
                                                                  pause_time=Duration.minutes(1)))
        self.role = role
