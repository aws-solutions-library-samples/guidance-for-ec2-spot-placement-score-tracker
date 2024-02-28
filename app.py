### Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
### SPDX-License-Identifier: MIT-0
###
### Permission is hereby granted, free of charge, to any person obtaining a copy of this
### software and associated documentation files (the "Software"), to deal in the Software
### without restriction, including without limitation the rights to use, copy, modify,
### merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
### permit persons to whom the Software is furnished to do so.
###
### THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
### INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
### PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
### HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
### OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
### SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# Author: Carlos Manzanedo Rueda <ruecarlo@amazon.com>

#!/usr/bin/env python3
import os

import aws_cdk
import aws_cdk as cdk
import aws_cdk.aws_lambda_python_alpha as lambda_python
from spot_placement_score_lambda import spot_placement_score_lambda as sps
from constructs import Construct
from aws_cdk import (
    Duration,
    Stack,
    aws_s3_assets,
    aws_lambda,
    aws_logs,
    aws_iam,
    aws_events,
    aws_events_targets,
    aws_cloudwatch,
    Names,
    CfnOutput,
    Aspects
)
from cdk_nag import (
    AwsSolutionsChecks,
    NagSuppressions
)

SPS_LAMBDA_ASSET_S3_BUCKET = 'sps-lambda-asset-s3-bucket'
CONTEXT_FILE_CONFIGURATION_KEY = 'sps-config'
CONTEXT_CDK_STACK_NAME_KEY = 'cfn-name'
DEFAULT_STACK_NAME = "spot-placement-score-dashboard"
DEFAULT_CONFIGURATION_FILE = './sps_configuration/sps_config.yaml'
COLOR_LIST = [
    '#1f77b4',
    '#ff7f0e',
    '#2ca02c',
    '#d62728',
    '#9467bd',
    '#8c564b',
    '#e377c2',
    '#7f7f7f',
    '#bcbd22',
    '#17becf',
    '#aec7e8',
    '#ffbb78',
    '#98df8a',
    '#ff9896',
    '#c5b0d5',
    '#c49c94',
    '#f7b6d2',
    '#c7c7c7',
    '#dbdb8d',
    '#9edae5'
]


class SpotPlacementScoreDashboardStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = aws_cdk.Environment.account
        region = aws_cdk.Environment.region

        configuration_file = self.node.try_get_context(CONTEXT_FILE_CONFIGURATION_KEY) \
            if self.node.try_get_context(CONTEXT_FILE_CONFIGURATION_KEY)\
            else DEFAULT_CONFIGURATION_FILE

        lambda_s3_configuration = aws_s3_assets.Asset(
            self,
            f"{SPS_LAMBDA_ASSET_S3_BUCKET}--{Names.unique_id(self)}",
            path=configuration_file
        )

        self.tags.set_tag("aws_solution_name", "SPS-Dashboard")
        self.tags.set_tag("sps-dashboard", self.to_string())

        sps_lambda_role = aws_iam.Role(
            self,
            f"SPS-lambda-role-{Names.unique_id(self)}",
            assumed_by=aws_iam.ServicePrincipal('lambda.amazonaws.com'),
        )

        read_from_s3_bucket_policy = aws_iam.PolicyStatement(
            effect=aws_iam.Effect.ALLOW,
            resources=[f"arn:aws:s3:::{lambda_s3_configuration.s3_bucket_name}/*"],
            actions=[
                's3:GetObject'
            ]
        )

        # Spot Placement Score support conditional iam property for regions
        # Customer can protect the regions that are selected by adding that
        # condition here
        read_sps_policy = aws_iam.PolicyStatement(
            effect=aws_iam.Effect.ALLOW,
            resources=['*'],
            actions=[
                'ec2:GetSpotPlacementScores'
            ]
        )

        put_to_cloudwatch = aws_iam.PolicyStatement(
            effect=aws_iam.Effect.ALLOW,
            resources=["*"],
            actions=[
                'cloudwatch:PutMetricData'
            ],
            conditions={
                "StringEquals": {
                    "cloudwatch:namespace": sps.SPS_METRIC_NAMESPACE
                }
            }
        )

        basic_lambda_policy_for_logs = aws_iam.PolicyStatement(
            effect=aws_iam.Effect.ALLOW,
            resources=["*"],
            actions=[
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents'
            ]
        )

        sps_lambda_role.add_to_policy(basic_lambda_policy_for_logs)
        sps_lambda_role.add_to_policy(read_sps_policy)
        sps_lambda_role.add_to_policy(read_from_s3_bucket_policy)
        sps_lambda_role.add_to_policy(put_to_cloudwatch)
        # The PutMetric data does only support protection by using the
        # Conditional for the namespace. I've restricted the namespace
        # to the only one allowed by our app
        # Additionally ec2:GetSpotPlacementScores is a read only API
        # that just does get the Spot placement score with no resource
        # allocated except regions... and in this case we definitely
        # want to have it to * as we want to query SPS across regions
        NagSuppressions.add_resource_suppressions(sps_lambda_role, [({
            'id': 'AwsSolutions-IAM5',
            'reason': 'Role used adheres to least privilege, PutMetricData does only '+
                      'support * parameter, but the code uses also a IAM conditional' +
                      'to restrict write operations to the ' + sps.SPS_METRIC_NAMESPACE +
                      'the other * is needed for the read method `ec2:GetSpotPlacementScores'})
        ], apply_to_children=True)

        sps_lambda_log_retention_role = aws_iam.Role(
            self,
            f"SPS-lambda-log-retention-role-{Names.unique_id(self)}",
            assumed_by=aws_iam.ServicePrincipal('lambda.amazonaws.com'),
        )

        log_retention_policy = aws_iam.PolicyStatement(
            effect=aws_iam.Effect.ALLOW,
            resources=["*"],
            actions=[
                'logs:DeleteRetentionPolicy',
                'logs:PutRetentionPolicy',
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents'
            ]
        )
        sps_lambda_log_retention_role.add_to_policy(log_retention_policy)
        NagSuppressions.add_resource_suppressions(sps_lambda_log_retention_role, [({
            'id': 'AwsSolutions-IAM5',
            'reason': 'Lambda for log cleaning requires access to the log group, same for rotation'})
        ], apply_to_children=True)

        sps_lambda = lambda_python.PythonFunction(
            self,
            f"SPS-score-function--{Names.unique_id(self)}",
            entry='./spot_placement_score_lambda/',
            index='spot_placement_score_lambda.py',
            handler='handler',
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            log_retention=aws_logs.RetentionDays.FIVE_DAYS,  # Retention logs for the lambda set to 5 days
            description="Spot Placement Score to Cloudwatch lambda, stores sps into cloudwatch",
            memory_size=256,
            profiling=False,  # Should be disabled for prod use
            timeout=Duration.seconds(300),
            environment={
                "S3_CONFIGURATION_BUCKET": lambda_s3_configuration.s3_bucket_name,
                "S3_CONFIGURATION_OBJECT_KEY": lambda_s3_configuration.s3_object_key
            },
            role=sps_lambda_role,
            log_retention_role=sps_lambda_log_retention_role,
            reserved_concurrent_executions=1
        )


        rule = aws_events.Rule(
            self,
            f"CollectSPS--{Names.unique_id(self)}",
            schedule=aws_events.Schedule.cron(
                minute='*/5',
                hour='*',
                month='*',
                week_day='*',
                year='*'),
        )
        rule.add_target(aws_events_targets.LambdaFunction(sps_lambda))

        # Setting the configuration for local execution
        os.environ[sps.DEBUG] = "true"
        os.environ[sps.DEBUG_CONFIG_FILE] = configuration_file
        dashboard_config_list = sps.loadConfigurations()
        dashboards = []
        # TODO: Run python cerberus validation on the configuration
        for dashboard_config in dashboard_config_list:
            widgets = []
            metric_colors = {}
            colour_counter = 0

            dashboard_name = dashboard_config['Dashboard']
            sps_configurations = dashboard_config['Sps']
            width = 24 if "DefaultWidgetWidth" not in dashboard_config else dashboard_config["DefaultWidgetWidth"]
            height = 6 if "DefaultWidgetHeight" not in dashboard_config else dashboard_config["DefaultWidgetHeight"]

            dashboard = aws_cloudwatch.Dashboard(
                self,
                f'{dashboard_name}-{Names.unique_id(self)}',
                dashboard_name=dashboard_name
            )

            for configuration in sps_configurations:
                distributed_config_metrics = []
                print(f"Processing: {configuration['ConfigurationName']}")
                # Create a list of cloudwatch metric objects, we need to collect
                # At least one SPS score to understand which metrics will be created
                # Specially considering the configuration might be using AZ and that will
                # Increase a lot the type of metrics and change the dimensions as well
                sps_scores = sps.fetchSPSScore(configuration)
                for score in sps_scores:
                    cloudwatch_metric_name = configuration['ConfigurationName']
                    unit_type = configuration['TargetCapacityUnitType']
                    target_capacity = configuration['TargetCapacity']
                    metric_name = f"{cloudwatch_metric_name}-{score['Region']}-{unit_type}-{target_capacity}"
                    dimensions = {
                        'Region': f"{score['Region']}",
                        'DiversificationName': f"{cloudwatch_metric_name}",
                        'UnitType': f"{unit_type}",
                        'TargetCapacity': f"{target_capacity}"
                    }
                    if 'AvailabilityZoneId' in score:
                        metric_name = f"{metric_name}-{score['AvailabilityZoneId']}"
                        dimensions['AvailabilityZoneId'] = score['AvailabilityZoneId']

                    color_hash = f"{score['Region']}{score['AvailabilityZoneId'] if 'AvailabilityZoneId' in score else '' }"
                    if color_hash in metric_colors:
                        color = metric_colors[color_hash]
                    else:
                        color = COLOR_LIST[colour_counter]
                        metric_colors[color_hash] = color
                        colour_counter += 1

                    distributed_config_metrics.append(aws_cloudwatch.Metric(
                        metric_name=metric_name,
                        namespace=sps.SPS_METRIC_NAMESPACE,
                        dimensions_map=dimensions,
                        label=metric_name,
                        period=aws_cdk.Duration.minutes(15),
                        statistic='max',
                        color=color
                    ))

                graph_widget = aws_cloudwatch.GraphWidget(
                    title=f"SPS for {configuration['ConfigurationName']}-{unit_type}-{target_capacity}",
                    left=distributed_config_metrics,
                    width=width,
                    height=height,
                    left_y_axis=aws_cloudwatch.YAxisProps(
                        label='SPS',
                        max=10,
                        min=0,
                        show_units=False
                    )
                )
                widgets.append(graph_widget)

            dashboard.add_widgets(*widgets)
            dashboards.append(dashboard)

        CfnOutput(self, "SPSLambdaARN", value=sps_lambda.function_arn)
        for dashboard in dashboards:
            sanitised_dashboard_name = dashboard.dashboard_name.lower().replace(" ", "_")[:max(len(dashboard.dashboard_name), 60)]
            CfnOutput(
                self,
                f'SPSDashboard-{sanitised_dashboard_name}',
                value=dashboard.dashboard_arn,
                description="Spot Placement Score Dashboard"
            )


app = cdk.App()

if app.node.try_get_context("cdk-nag"):
    Aspects.of(app).add(AwsSolutionsChecks(verbose=True))

spot_placement_score_dashboard_stack = SpotPlacementScoreDashboardStack(
    app,
    "spot-placement-score-dashboard",
    stack_name=app.node.try_get_context("stack-name"),
    description="Guidance for EC2 Spot Placement Score AWS (SO9399)"
)
app.synth()