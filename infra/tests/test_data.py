from aws_cdk.assertions import Match


def test_bucket_is_private_encrypted_ssl_only_and_retained(templates):
    t = templates["data"]
    t.has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": {"BlockPublicAcls": True, "BlockPublicPolicy": True,
                                           "IgnorePublicAcls": True, "RestrictPublicBuckets": True},
        "BucketEncryption": {"ServerSideEncryptionConfiguration": [
            {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
    })
    t.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain"})
    t.has_resource_properties("AWS::S3::BucketPolicy", {"PolicyDocument": {"Statement": Match.array_with([
        Match.object_like({"Effect": "Deny", "Condition": {"Bool": {"aws:SecureTransport": "false"}}})])}})


def test_lifecycle_rules(templates):
    templates["data"].has_resource_properties("AWS::S3::Bucket", {"LifecycleConfiguration": {"Rules": Match.array_with([
        Match.object_like({"Id": "exports-30d", "Prefix": "exports/", "ExpirationInDays": 30, "Status": "Enabled"}),
        Match.object_like({"Id": "abort-mpu", "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1}})])}})


def test_not_versioned_litestream_manages_generations(templates):
    props = [r["Properties"] for r in templates["data"].find_resources("AWS::S3::Bucket").values()][0]
    assert "VersioningConfiguration" not in props


def test_bucket_name_is_published_for_the_scripts(templates):
    templates["data"].has_resource_properties("AWS::SSM::Parameter", {"Name": "/navi/prod/bucket", "Type": "String"})


def test_data_stack_has_termination_protection(stacks):
    assert stacks["data"].termination_protection is True
