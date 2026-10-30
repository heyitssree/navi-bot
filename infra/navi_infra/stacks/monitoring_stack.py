"""Monitoring: a missing-heartbeat alarm and a monthly AWS Budget, both emailing the owner through SNS / Budgets."""
from aws_cdk import Duration, Stack, aws_budgets as budgets, aws_cloudwatch as cw, aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_sns as sns, aws_sns_subscriptions as subs
from constructs import Construct

from navi_infra.config import NaviConfig


class MonitoringStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: NaviConfig, asg, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.topic = sns.Topic(self, "Alerts", display_name=f"Navi {cfg.env_name} alerts")
        self.topic.add_subscription(subs.EmailSubscription(cfg.alert_email))     # the owner must confirm the first email

        heartbeat = cw.Metric(
            namespace="Navi", metric_name="Heartbeat", dimensions_map={"Env": cfg.env_name},
            statistic="SampleCount", period=Duration.minutes(5))
        self.alarm = cw.Alarm(
            self, "BotDown", metric=heartbeat, threshold=1,
            comparison_operator=cw.ComparisonOperator.LESS_THAN_THRESHOLD, evaluation_periods=3,
            treat_missing_data=cw.TreatMissingData.BREACHING,
            alarm_description="No Navi heartbeat for 15 minutes (bot down, idling with run_enabled=false, or replaced)")
        self.alarm.add_alarm_action(cw_actions.SnsAction(self.topic))

        budgets.CfnBudget(
            self, "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=cfg.name("monthly"), budget_type="COST", time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=cfg.monthly_budget_usd, unit="USD")),  # AISPL accounts: confirm the unit
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type=kind, comparison_operator="GREATER_THAN", threshold=pct, threshold_type="PERCENTAGE"),
                    subscribers=[budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=cfg.alert_email)])
                for kind, pct in (("ACTUAL", 80), ("FORECASTED", 100))])
