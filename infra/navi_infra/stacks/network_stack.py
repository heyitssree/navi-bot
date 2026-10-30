"""Network: one public subnet in one AZ, no NAT gateway, no inbound rules (administration is via SSM Session Manager)."""
from aws_cdk import Stack, aws_ec2 as ec2
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, az: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.vpc = ec2.Vpc(
            self, "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.40.0.0/24"),
            availability_zones=[az],             # one AZ, named explicitly so synth never calls AWS
            nat_gateways=0,                      # no NAT: saves ~$30+/month
            subnet_configuration=[ec2.SubnetConfiguration(
                name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=26)],
        )
        # Free gateway endpoint: Litestream's S3 traffic stays on the AWS network
        self.vpc.add_gateway_endpoint("S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3)
