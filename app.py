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
# Author: Carlos Manzanedo Rueda <ruecarlo@amazon.com>, Yael Grossman <yaelgr@amazon.com>

#!/usr/bin/env python3
import os
import json

import aws_cdk as cdk

from constructs import Construct


from aws_cdk import (
    Duration, Stack, aws_s3_assets, aws_lambda, aws_iam,
    aws_events, aws_events_targets, aws_cloudwatch, Names, CfnOutput
)

from aws_cdk.aws_lambda_python_alpha import PythonFunction

CONTEXT_CUSTOM_CONFIG_KEY = 'custom-config'
CONTEXT_KARPENTER_CONFIG_KEY = 'karpenter-config'
CONTEXT_STACK_NAME_KEY = 'stack-name'
DEFAULT_CUSTOM_CONFIG = './configuration/custom_config.yaml'
DEFAULT_KARPENTER_CONFIG = './configuration/karpenter_nodepools_config.yaml'
DEFAULT_STACK_NAME = 'unified-spot-tracker'

DEPLOYMENT_NAME = "v1"

class UnifiedSpotTrackerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Generate spot configuration
        configuration_file = self.generate_spot_config()
        print(f"Creating S3 asset for: {configuration_file}")
        lambda_s3_configuration = aws_s3_assets.Asset(
            self, "sps-lambda-asset", path=configuration_file)
        print("S3 asset created successfully")

        # Create all Lambda functions
        print("Creating SPS lambda...")
        self.create_sps_lambda(lambda_s3_configuration, DEPLOYMENT_NAME)
        
        # Create event rules
        print("Creating event rules...")
        self.create_event_rules(DEPLOYMENT_NAME)
        
        # Create unified dashboard
        print("Creating unified dashboard...")
        self.create_unified_dashboard(DEPLOYMENT_NAME)
        print("Stack creation completed")

        CfnOutput(self, "SPSLambdaARN", value=self.sps_lambda.function_arn)

    def generate_spot_config(self):
        """Generate spot_config.yaml from unified configuration"""
        import subprocess
        import os
        
        # Get custom config paths from CDK context
        custom_config = self.node.try_get_context(CONTEXT_CUSTOM_CONFIG_KEY) or DEFAULT_CUSTOM_CONFIG
        karpenter_config = self.node.try_get_context(CONTEXT_KARPENTER_CONFIG_KEY) or DEFAULT_KARPENTER_CONFIG
        
        # Validate paths to prevent command injection
        if not custom_config.endswith('.yaml') and not custom_config.endswith('.yml'):
            raise ValueError(f"Invalid custom config path: {custom_config}")
        if not karpenter_config.endswith('.yaml') and not karpenter_config.endswith('.yml'):
            raise ValueError(f"Invalid karpenter config path: {karpenter_config}")
        
        print(f"Using custom config: {custom_config}")
        print(f"Using karpenter config: {karpenter_config}")
        print("Running workloads_detection.py...")
        
        cmd = ['python3', 'workloads_detection.py']
        if custom_config != DEFAULT_CUSTOM_CONFIG:
            cmd.extend(['--custom-config', custom_config])
        if karpenter_config != DEFAULT_KARPENTER_CONFIG:
            cmd.extend(['--karpenter-config', karpenter_config])
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd='.', shell=False)
        if result.returncode != 0:
            print(f"workloads_detection.py stderr: {result.stderr}")
            print(f"workloads_detection.py stdout: {result.stdout}")
            raise Exception(f"workloads_detection.py failed: {result.stderr}")
        
        print(f"Generated configuration: {result.stdout}")
        return './configuration/spot_config.yaml'

    def create_sps_lambda(self, lambda_s3_configuration, suffix):
        """Create SPS Lambda with required permissions"""
        sps_lambda_role = aws_iam.Role(
            self, "SPS-lambda-role",
            assumed_by=aws_iam.ServicePrincipal('lambda.amazonaws.com'))

        sps_lambda_role.add_to_policy(aws_iam.PolicyStatement(
            effect=aws_iam.Effect.ALLOW, resources=["*"],
            actions=['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents']))
        
        sps_lambda_role.add_to_policy(aws_iam.PolicyStatement(
            effect=aws_iam.Effect.ALLOW, resources=['*'],
            actions=['ec2:GetSpotPlacementScores', 'ec2:DescribeSpotPriceHistory', 
                    'ec2:DescribeInstanceTypes', 'ec2:DescribeAvailabilityZones',
                    'ec2:GetInstanceTypesFromInstanceRequirements']))
        
        sps_lambda_role.add_to_policy(aws_iam.PolicyStatement(
            effect=aws_iam.Effect.ALLOW, resources=["*"],
            actions=['cloudwatch:PutMetricData'],
            conditions={"StringEquals": {"cloudwatch:namespace": "Spot Placement Score Metrics"}}))
        
        sps_lambda_role.add_to_policy(aws_iam.PolicyStatement(
            effect=aws_iam.Effect.ALLOW,
            resources=[f"arn:aws:s3:::{lambda_s3_configuration.s3_bucket_name}/*"],
            actions=['s3:GetObject']))

        print("Creating Lambda Function...")
        self.sps_lambda = PythonFunction(
            self, "SPS-function",
            entry='./spot_placement_score_lambda/',
            index='spot_placement_score_lambda_v2.py',
            handler='handler',
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            architecture=aws_lambda.Architecture.ARM_64, memory_size=512,
            timeout=Duration.seconds(600), role=sps_lambda_role,
            environment={
                "S3_CONFIGURATION_BUCKET": lambda_s3_configuration.s3_bucket_name,
                "S3_CONFIGURATION_OBJECT_KEY": lambda_s3_configuration.s3_object_key})
        print("Lambda Function created successfully")

    def create_interruption_lambdas(self, suffix):
        """Create interruption tracking lambdas"""
        pass  # Placeholder - interruption tracking disabled

    def create_cross_region_replication(self, suffix):
        """Create cross-region replication for interruption events"""
        pass  # Placeholder - cross-region replication disabled

    def create_event_rules(self, suffix):
        """Create EventBridge rules"""
        # SPS Collection Schedule
        aws_events.Rule(self, "CollectSPS", schedule=aws_events.Schedule.cron(
            minute='*/15', hour='*', month='*', week_day='*', year='*')
        ).add_target(aws_events_targets.LambdaFunction(self.sps_lambda))

    def create_unified_dashboard(self, suffix):
        """Create SPS dashboard with placement score and pricing widgets"""
        # Load spot config to get dynamic values
        import yaml
        with open('./configuration/spot_config.yaml', 'r') as f:
            spot_config = yaml.safe_load(f)
        
        # Get regions from spot config
        regions = spot_config.get('default_regions', ["eu-north-1", "eu-west-1", "eu-south-1", "us-west-2", "us-east-1"])
        
        # Get unique diversification names from all configurations
        diversification_names = set()
        target_capacities = set()
        unit_types = set()
        workload_types = set()
        
        for dashboard in spot_config.get('dashboards', []):
            for sps_config in dashboard.get('Sps', []):
                diversification_names.add(sps_config.get('ConfigurationName', ''))
                workload_types.add(sps_config.get('WorkloadType', 'Custom'))
                unit_types.add(sps_config.get('TargetCapacityUnitType', 'vcpu'))
                # Handle TargetCapacity as list or single value
                tc = sps_config.get('TargetCapacity', [])
                if isinstance(tc, list):
                    target_capacities.update(str(x) for x in tc)
                else:
                    target_capacities.add(str(tc))
        
        # Convert to sorted lists and create dropdown values
        diversification_values = [{"label": name, "value": name} for name in sorted(diversification_names) if name]
        capacity_values = [{"label": cap, "value": cap} for cap in sorted(target_capacities, key=int)]
        unit_values = [{"label": unit, "value": unit} for unit in sorted(unit_types)]
        workload_values = [{"label": wl, "value": wl} for wl in sorted(workload_types)]
        
        # Get first Custom workload alphabetically for default
        custom_names = {sps.get('ConfigurationName') for dash in spot_config.get('dashboards', []) 
                       for sps in dash.get('Sps', []) if sps.get('WorkloadType') == 'Custom'}
        default_diversification = next((v['value'] for v in diversification_values if v['value'] in custom_names), 
                                      diversification_values[0]['value'] if diversification_values else "")
        default_capacity = capacity_values[0]['value'] if capacity_values else "100"
        
        # Create SPS metrics for all regions
        best_time_metrics = []
        score_metrics = []
        price_metrics = []
        
        for region in regions:
            best_time_metrics.append([
                "Spot Placement Score Metrics", "Score", 
                "WorkloadType", "${WorkloadType}", 
                "TargetCapacity", "${TargetCapacity}", 
                "UnitType", "${UnitType}", 
                "DiversificationName", "${DiversificationName}", 
                "Region", region,
                "MetricType", "Score",
                {"label": region, "region": self.region}
            ])
            
            score_metrics.append([
                "Spot Placement Score Metrics", "Score", 
                "WorkloadType", "${WorkloadType}", 
                "TargetCapacity", "${TargetCapacity}", 
                "UnitType", "${UnitType}", 
                "DiversificationName", "${DiversificationName}", 
                "Region", region,
                "MetricType", "Score",
                {"stat": "Maximum", "label": f"{region} Score", "region": self.region}
            ])
            
            price_metrics.append([
                "Spot Placement Score Metrics", "Price", 
                "WorkloadType", "${WorkloadType}", 
                "DiversificationName", "${DiversificationName}", 
                "Region", region,
                "MetricType", "Price",
                {"stat": "Maximum", "label": f"{region} Price", "region": self.region}
            ])
        
        dashboard_body = {
            "variables": [
                {
                    "type": "property",
                    "property": "WorkloadType",
                    "inputType": "select",
                    "id": "WorkloadType",
                    "label": "Workload Type",
                    "values": workload_values,
                    "defaultValue": "Custom"
                },
                {
                    "type": "property",
                    "property": "DiversificationName",
                    "inputType": "select",
                    "id": "DiversificationName",
                    "label": "Configuration Name",
                    "values": diversification_values,
                    "defaultValue": default_diversification
                },
                {
                    "type": "property",
                    "property": "TargetCapacity",
                    "inputType": "select",
                    "id": "TargetCapacity",
                    "label": "Target Capacity",
                    "values": capacity_values,
                    "defaultValue": default_capacity
                },
                {
                    "type": "property",
                    "property": "UnitType",
                    "inputType": "select",
                    "id": "UnitType",
                    "label": "Unit Type",
                    "values": unit_values,
                    "defaultValue": "vcpu"
                }
            ],
            "widgets": [
                # SPS Section
                {
                    "type": "text",
                    "x": 0,
                    "y": 0,
                    "width": 24,
                    "height": 5,
                    "properties": {
                        "markdown": "## EC2 Spot placement score and pricing analysis\n\nThe EC2 Spot placement score helps evaluate the probability of your Spot Instance requests being fulfilled in specific Region by providing a score from 0 to 10, based on capacity usage patterns. By analyzing these scores over time, you can make data-driven decisions to identify optimal times of day and week to deploy your workloads, maximizing Spot availability while minimizing both interruptions and costs.\n\nAverage Spot placement scores help you choose the optimal region for your workload deployment. Spot capacity fluctuates, and this average score provides an indicator of where your workload has the highest chances to maintain operation over time. A higher score indicates a better choice for your deployment.\n\nFor time-flexible workloads, combine the SPS and Price trend charts to identify the most available and cost-effective times to run your workload. This data-driven approach helps maximize availability while minimizing both interruptions and costs.",
                        "transparent": True
                    }
                },
                {
                    "type": "metric",
                    "x": 0,
                    "y": 5,
                    "width": 24,
                    "height": 4,
                    "properties": {
                        "metrics": best_time_metrics,
                        "view": "gauge",
                        "region": self.region,
                        "title": "Average SPS Scores by Region (Weekly)",
                        "period": 604800,
                        "stat": "Average",
                        "yAxis": {
                            "left": {
                                "min": 1,
                                "max": 10
                            }
                        },
                        "annotations": {
                            "horizontal": [
                                {
                                    "value": 6,
                                    "color": "#d62728",
                                    "fill": "below"
                                },
                                {
                                    "value": 6,
                                    "color": "#2ca02c",
                                    "fill": "above"
                                }
                            ]
                        },
                        "legend": {
                            "position": "bottom"
                        }
                    }
                },
                {
                    "type": "metric",
                    "x": 0,
                    "y": 9,
                    "width": 12,
                    "height": 6,
                    "properties": {
                        "metrics": score_metrics,
                        "view": "timeSeries",
                        "stacked": False,
                        "region": self.region,
                        "title": "SPS Scores by Region",
                        "period": 300,
                        "yAxis": {
                            "left": {
                                "min": 1,
                                "max": 10,
                                "label": "SPS Score"
                            }
                        }
                    }
                },
                {
                    "type": "metric",
                    "x": 12,
                    "y": 9,
                    "width": 12,
                    "height": 6,
                    "properties": {
                        "metrics": price_metrics,
                        "view": "timeSeries",
                        "stacked": False,
                        "region": self.region,
                        "title": "Spot Prices by Region",
                        "period": 300,
                        "yAxis": {
                            "left": {
                                "min": 0,
                                "label": "Price ($)"
                            }
                        }
                    }
                }
            ]
        }

        dashboard_name = f"{Names.unique_id(self)}-Dashboard"
        aws_cloudwatch.CfnDashboard(
            self, "UnifiedSpotDashboard", dashboard_name=dashboard_name,
            dashboard_body=json.dumps(dashboard_body))
        
        CfnOutput(self, "DashboardName", value=dashboard_name)

app = cdk.App()
stack_name = app.node.try_get_context(CONTEXT_STACK_NAME_KEY) or DEFAULT_STACK_NAME
UnifiedSpotTrackerStack(
    app,
    stack_name,
    stack_name=stack_name,
    description="Guidance for EC2 Spot Placement Score AWS (SO9399)"
)
app.synth()
