from aws_cdk.assertions import Match


def test_single_az_vpc_with_no_nat_and_no_elastic_ip(templates):
    t = templates["net"]
    t.resource_count_is("AWS::EC2::VPC", 1)
    t.resource_count_is("AWS::EC2::Subnet", 1)
    t.resource_count_is("AWS::EC2::NatGateway", 0)
    t.resource_count_is("AWS::EC2::EIP", 0)
    t.has_resource_properties("AWS::EC2::VPC", {"CidrBlock": "10.40.0.0/24"})
    t.has_resource_properties("AWS::EC2::Subnet", {"AvailabilityZone": "ap-south-1a", "MapPublicIpOnLaunch": True})


def test_free_s3_gateway_endpoint(templates):
    templates["net"].has_resource_properties("AWS::EC2::VPCEndpoint", {
        "VpcEndpointType": "Gateway", "ServiceName": Match.object_like({"Fn::Join": Match.any_value()})})


def test_no_inbound_rules_anywhere(templates):
    for t in templates.values():
        t.resource_count_is("AWS::EC2::SecurityGroupIngress", 0)
