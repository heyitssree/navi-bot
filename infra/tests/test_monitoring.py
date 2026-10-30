from aws_cdk.assertions import Match


def test_heartbeat_alarm(templates):
    templates["mon"].has_resource_properties("AWS::CloudWatch::Alarm", {
        "Namespace": "Navi", "MetricName": "Heartbeat", "Dimensions": [{"Name": "Env", "Value": "prod"}],
        "Statistic": "SampleCount", "Period": 300, "EvaluationPeriods": 3, "Threshold": 1,
        "ComparisonOperator": "LessThanThreshold", "TreatMissingData": "breaching",
        "AlarmActions": [Match.object_like({"Ref": Match.any_value()})]})


def test_email_subscription_to_the_owner(templates):
    templates["mon"].has_resource_properties("AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "owner@example.com"})


def test_monthly_budget_with_two_email_alerts(templates):
    t = templates["mon"]
    t.has_resource_properties("AWS::Budgets::Budget", {"Budget": Match.object_like({
        "BudgetType": "COST", "TimeUnit": "MONTHLY", "BudgetLimit": {"Amount": 15, "Unit": "USD"}})})
    notes = next(iter(t.find_resources("AWS::Budgets::Budget").values()))["Properties"]["NotificationsWithSubscribers"]
    assert [(n["Notification"]["NotificationType"], n["Notification"]["Threshold"]) for n in notes] == [("ACTUAL", 80), ("FORECASTED", 100)]
    assert all(n["Subscribers"] == [{"SubscriptionType": "EMAIL", "Address": "owner@example.com"}] for n in notes)


def test_budget_amount_follows_config():
    from aws_cdk.assertions import Template

    from tests.conftest import build, make_cfg

    t = Template.from_stack(build(make_cfg(monthly_budget_usd=40))["mon"])
    t.has_resource_properties("AWS::Budgets::Budget", {"Budget": Match.object_like({"BudgetLimit": {"Amount": 40, "Unit": "USD"}})})
