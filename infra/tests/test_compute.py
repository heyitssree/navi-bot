import json
from pathlib import Path

from aws_cdk.assertions import Match


def _statements(t):
    out = []
    for pol in t.find_resources("AWS::IAM::Policy").values():
        out += pol["Properties"]["PolicyDocument"]["Statement"]
    return out


def _by_sid(t):
    return {s["Sid"]: s for s in _statements(t) if "Sid" in s}


def test_single_instance_and_no_inbound(templates):
    t = templates["compute"]
    t.has_resource_properties("AWS::AutoScaling::AutoScalingGroup", {"MinSize": "1", "MaxSize": "1"})
    t.has_resource_properties("AWS::EC2::SecurityGroup", {"SecurityGroupIngress": Match.absent()})
    t.resource_count_is("AWS::EC2::SecurityGroupIngress", 0)


def test_rolling_update_never_runs_two_bots_at_once(templates):
    templates["compute"].has_resource("AWS::AutoScaling::AutoScalingGroup", {"UpdatePolicy": {
        "AutoScalingRollingUpdate": Match.object_like({"MinInstancesInService": 0, "MaxBatchSize": 1})}})


def test_imdsv2_with_hop_limit_two(templates):
    templates["compute"].has_resource_properties("AWS::EC2::LaunchTemplate", {"LaunchTemplateData": Match.object_like(
        {"MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 2}})})


def test_graviton_instance_with_public_ip_and_encrypted_gp3_root(templates):
    t = templates["compute"]
    t.has_resource_properties("AWS::EC2::LaunchTemplate", {"LaunchTemplateData": Match.object_like({
        "InstanceType": "t4g.micro",
        "NetworkInterfaces": Match.array_with([Match.object_like({"AssociatePublicIpAddress": True})]),
        "BlockDeviceMappings": [{"DeviceName": "/dev/xvda", "Ebs": {
            "VolumeSize": 10, "VolumeType": "gp3", "Encrypted": True, "DeleteOnTermination": True}}]})})
    t.has_resource_properties("AWS::EC2::LaunchTemplate", {"LaunchTemplateData": Match.not_({"InstanceMarketOptions": Match.any_value()})})
    assert "arm64" in json.dumps(t.to_json()["Parameters"])


def test_spot_is_opt_in():
    from aws_cdk.assertions import Template

    from tests.conftest import build, make_cfg

    t = Template.from_stack(build(make_cfg(use_spot=True))["compute"])
    t.has_resource_properties("AWS::EC2::LaunchTemplate", {"LaunchTemplateData": Match.object_like({
        "InstanceMarketOptions": Match.object_like({"MarketType": "spot"})})})


def test_no_elastic_ip_no_nat_no_ssh(templates):
    for t in templates.values():
        t.resource_count_is("AWS::EC2::EIP", 0)
        t.resource_count_is("AWS::EC2::NatGateway", 0)
    flat = json.dumps(templates["compute"].to_json())
    assert '"FromPort": 22' not in flat and '"ToPort": 22' not in flat and "ssh" not in flat.lower().replace("sshd", "")


def test_session_manager_instead_of_ssh(templates):
    templates["compute"].has_resource_properties("AWS::IAM::Role", {"ManagedPolicyArns": Match.array_with([
        Match.object_like({"Fn::Join": Match.array_with([Match.array_with([Match.string_like_regexp(".*AmazonSSMManagedInstanceCore")])])})])})


def test_log_group_has_two_week_retention(templates):
    templates["compute"].has_resource_properties("AWS::Logs::LogGroup", {"LogGroupName": "/navi/prod/bot", "RetentionInDays": 14})


def test_image_uri_parameter_exists(templates):
    templates["compute"].has_resource_properties("AWS::SSM::Parameter", {"Name": "/navi/prod/image_uri", "Type": "String"})


def test_bedrock_is_limited_to_the_configured_profile_and_model(templates):
    stmts = _by_sid(templates["compute"])
    profile = {"Fn::Join": ["", ["arn:aws:bedrock:ap-south-1:111111111111:inference-profile/global.anthropic.claude-haiku-5-5"]]}
    flat = json.dumps(stmts)
    assert "bedrock:*" not in flat and '"Resource": "*"' not in json.dumps({k: v for k, v in stmts.items() if k.startswith("Bedrock")})
    in_region = stmts["BedrockModelInRegion"]
    assert in_region["Resource"] == "arn:aws:bedrock:ap-south-1::foundation-model/anthropic.claude-haiku-5-5"
    assert "bedrock:InferenceProfileArn" in in_region["Condition"]["StringEquals"]
    glob = stmts["BedrockModelGlobal"]
    assert glob["Resource"] == "arn:aws:bedrock:::foundation-model/anthropic.claude-haiku-5-5"
    assert glob["Condition"]["StringEquals"]["aws:RequestedRegion"] == "unspecified"
    assert sorted(stmts["BedrockProfileInRegion"]["Action"]) == ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    assert "global.anthropic.claude-haiku-5-5" in json.dumps(stmts["BedrockProfileInRegion"]["Resource"])
    assert stmts["BedrockStartupCheck"]["Action"] == "bedrock:GetInferenceProfile"
    del profile


def test_parameter_store_access_is_scoped_to_the_navi_prefix(templates):
    stmts = _by_sid(templates["compute"])
    read = stmts["ReadNaviParameters"]
    assert sorted(read["Action"]) == ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    assert "parameter/navi/prod/*" in json.dumps(read["Resource"])
    assert stmts["DecryptParametersViaSsm"]["Condition"] == {"StringEquals": {"kms:ViaService": "ssm.ap-south-1.amazonaws.com"}}


def test_heartbeat_metric_permission_is_limited_to_the_navi_namespace(templates):
    hb = _by_sid(templates["compute"])["Heartbeat"]
    assert hb["Action"] == "cloudwatch:PutMetricData" and hb["Condition"] == {"StringEquals": {"cloudwatch:namespace": "Navi"}}


def test_role_can_use_the_bucket_logs_and_ecr(templates):
    flat = json.dumps(_statements(templates["compute"]))
    for needle in ("s3:GetObject", "s3:PutObject", "s3:DeleteObject", "logs:PutLogEvents", "ecr:BatchGetImage", "ecr:GetAuthorizationToken"):
        assert needle in flat, needle


def test_no_secrets_in_user_data_or_the_template(templates):
    flat = json.dumps(templates["compute"].to_json()).lower()
    for needle in ("discord_token", "api_key", "aws_secret_access_key", "private key", "akia", "bot_token"):
        assert needle not in flat, needle


def test_user_data_wires_the_runtime(templates):
    ud = json.dumps(next(iter(templates["compute"].find_resources("AWS::EC2::LaunchTemplate").values()))
                    ["Properties"]["LaunchTemplateData"]["UserData"])
    for needle in ("NAVI_SSM_PREFIX=/navi/prod", "LITESTREAM_ENABLED=1", "LOG_TO_FILE=0", "BEDROCK_MODEL_ID=global.anthropic.claude-haiku-5-5",
                   "/opt/navi/update.sh", "navi.service", "fallocate -l 1G /swapfile", "chown 10001:10001 /var/lib/navi", "LOG_GROUP="):
        assert needle in ud, needle
    for placeholder in ("__REGION__", "__BUCKET__", "__ENV__", "__LOG_GROUP__", "__IMAGE_PARAM__", "__UPDATE_SH__", "__NAVI_SERVICE__"):
        assert placeholder not in ud, placeholder
    assert ud.count("#!/bin/bash") == 2                                  # the shebang from UserData plus the one inside update.sh
    assert '{\"Ref\": \"BotLogs' in ud or '"Ref": "BotLogs' in ud or "BotLogs" in ud           # log group name is a deploy-time reference


def test_image_asset_is_arm64_and_excludes_private_files(stacks):
    from navi_infra.stacks.compute_stack import IMAGE_EXCLUDES

    assert {".env*", "data", "*.db", ".git"} <= set(IMAGE_EXCLUDES)
    directory = stacks["compute"].node.root.synth().directory
    manifest = json.loads((Path(directory) / "C.assets.json").read_text())
    images = manifest["dockerImages"].values()
    assert images and all(i["source"]["platform"] == "linux/arm64" for i in images)
