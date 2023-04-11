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

import json
import logging
import os
import boto3
import sys
import yaml

logger = logging.getLogger()
logger.setLevel(logging.INFO)

handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

S3_CONFIGURATION_BUCKET_ENV_NAME = "S3_CONFIGURATION_BUCKET"
S3_CONFIGURATION_OBJECT_KEY = "S3_CONFIGURATION_OBJECT_KEY"
SPS_METRIC_NAMESPACE = "Spot Placement Score Metrics"
DEBUG = 'DEBUG'
DEBUG_CONFIG_FILE = 'DEBUG_CONFIG_FILE'

# Note a single configuration does support either a list of InstanceTypes
# Or an object that defines attribute instance selection InstanceRequirementsWithMetadata
# as defined here:
# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.get_spot_placement_scores



def loadConfigurations():
    """
    Loads the configuration from an S3 bucket. The configuration is expected to exist
    in a file named 'sps_config.yaml' and have a structure similar to the one commented
    above in this file. The configuration maps very closely with the Boto3 API for
    [Spot placement score](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.get_spot_placement_scores)
    :return: a list with the diversified configurations that will be processed by SPS
    and added to cloudwatch
    """
    if os.getenv(DEBUG) is not None:
        # debug mode allows us to load the configuration file from a local file
        configuration_path = os.getenv(DEBUG_CONFIG_FILE)
        if configuration_path is not None and os.path.isfile(configuration_path):
            logger.info(f"Debug mode detected, loading configuration from {configuration_path}")
            with open(configuration_path, 'r') as file:
                config_yaml = yaml.load(file.read(), Loader=yaml.loader.SafeLoader)
                logger.debug("Configuration successfully parsed from yaml to object")
                return config_yaml
        else:
            logger.error(f"Debug mode could not find the path for file {configuration_path}")

    s3_bucket = os.getenv(S3_CONFIGURATION_BUCKET_ENV_NAME)
    if s3_bucket is None:
        msg = f"Could not find required environment variable {S3_CONFIGURATION_BUCKET_ENV_NAME}"
        logger.error(msg)
        raise Exception(msg)

    s3_object = os.getenv(S3_CONFIGURATION_OBJECT_KEY)
    if s3_object is None:
        msg = f"Could not find required environment variable {S3_CONFIGURATION_OBJECT_KEY}"
        logger.error(msg)
        raise Exception(msg)

    logger.info(f"About to fetch configuration from bucket {s3_bucket}")
    s3_client = boto3.client('s3')
    response = s3_client.get_object(
        Bucket=s3_bucket,
        Key=s3_object
    )

    status_code = response['ResponseMetadata']['HTTPStatusCode']
    logger.info(f"Response Code: {status_code}")
    if status_code != 200:
        msg = f"Could not retrieve the s3://{s3_bucket}/{S3_CONFIGURATION_FILE_NAME}"
        logger.error(msg)
        raise Exception(msg)

    config_doc = response['Body'].read()
    config_yaml = yaml.load(config_doc, Loader=yaml.loader.SafeLoader)
    logger.debug("Configuration successfully parsed from yaml to object")
    return config_yaml


def __validateConfiguration(configuration=None):
    # For the moment I'll leave a pretty dumb  validation function,
    # But in the future this should hold a schema that verifies the configuration
    # Section using schema libraries such as [Cerberus](https://docs.python-cerberus.org/en/stable/)
    if configuration is None:
        msg = f"Configuration does not exist or is malformed"
        logger.error(msg)
        return msg

    missing_fields = []
    for key in ['ConfigurationName', 'TargetCapacity', 'TargetCapacityUnitType',
                'SingleAvailabilityZone', 'RegionNames']:
        if key not in configuration:
            missing_fields.append(key)

    if 'InstanceTypes' not in configuration and 'InstanceRequirementsWithMetadata' not in configuration:
        missing_fields.append('InstanceTypes or InstanceRequirementsWithMetadata')

    if not missing_fields:
        return None
    else:
        return f"The configuration is missing a few fields. Fields missing : {missing_fields}"


def fetchSPSScore(configuration=None):
    ec2_client = boto3.client('ec2')
    response = None
    if 'InstanceTypes' in configuration:
        response = ec2_client.get_spot_placement_scores(
            TargetCapacity=configuration['TargetCapacity'],
            InstanceTypes=configuration['InstanceTypes'],
            TargetCapacityUnitType=configuration['TargetCapacityUnitType'],
            SingleAvailabilityZone=configuration['SingleAvailabilityZone'],
            RegionNames=configuration['RegionNames']
        )
    else:
        response = ec2_client.get_spot_placement_scores(
            TargetCapacity=configuration['TargetCapacity'],
            InstanceRequirementsWithMetadata=configuration['InstanceRequirementsWithMetadata'],
            TargetCapacityUnitType=configuration['TargetCapacityUnitType'],
            SingleAvailabilityZone=configuration['SingleAvailabilityZone'],
            RegionNames=configuration['RegionNames']
        )
    status_code = response['ResponseMetadata']['HTTPStatusCode']
    logger.info(f"Response Code: {status_code}")
    if status_code != 200:
        logger.error("Could not retrieve the Spot Placement Score")

    spot_placement_scores = response['SpotPlacementScores']
    logger.debug(f"Got response : {response}")
    logger.info(f"Spot Placement Score: {spot_placement_scores}")
    return spot_placement_scores


def __putSPSMetricsInCloudwatch(configuration, spot_placement_scores=None):
    if spot_placement_scores is None:
        msg = "Spot Placement Scores was None, cannot insert in cloudwatch"
        raise Exception(msg)

    cloudwatch_client = boto3.client('cloudwatch')
    cloudwatch_metric_name = configuration['ConfigurationName']
    target_capacity = configuration['TargetCapacity']
    unit_type = configuration['TargetCapacityUnitType']

    # if 'AvailabilityZoneId' not in score else f"{cloudwatch_metric_name}-{score['Region']}-{unit_type}-{target_capacity}-{score['AvailabilityZoneId']}"

    metric_data = [
        {
            'MetricName': f"{cloudwatch_metric_name}-{score['Region']}-{unit_type}-{target_capacity}"
            if 'AvailabilityZoneId' not in score else
            f"{cloudwatch_metric_name}-{score['Region']}-{unit_type}-{target_capacity}-{score['AvailabilityZoneId']}",
            'Dimensions': [
                {
                    'Name': 'Region',
                    'Value': f"{score['Region']}"
                },
                {
                    'Name': 'DiversificationName',
                    'Value': f"{cloudwatch_metric_name}"
                },
                {
                    'Name': 'UnitType',
                    'Value': f"{unit_type}"
                },
                {
                    'Name': 'TargetCapacity',
                    'Value': f"{target_capacity}"
                }
            ] if 'AvailabilityZoneId' not in score else [
                {
                    'Name': 'Region',
                    'Value': f"{score['Region']}"
                },
                {
                    'Name': 'DiversificationName',
                    'Value': f"{cloudwatch_metric_name}"
                },
                {
                    'Name': 'UnitType',
                    'Value': f"{unit_type}"
                },
                {
                    'Name': 'TargetCapacity',
                    'Value': f"{target_capacity}"
                },
                {
                    'Name': 'AvailabilityZoneId',
                    'Value': score['AvailabilityZoneId']
                }
            ]
            ,
            'Unit': 'Count',
            'Value': score['Score']}
        for score in spot_placement_scores
    ]
    logger.debug(f"Metric data value: {metric_data}")

    response = cloudwatch_client.put_metric_data(
        MetricData=metric_data,
        Namespace=SPS_METRIC_NAMESPACE
    )

    logger.debug(f"Got response {response}")
    status_code = response['ResponseMetadata']['HTTPStatusCode']
    if status_code != 200:
        logger.error("Could not store metrics to cloudwatch")
    logger.info(f"Data stored to cloudwatch")
    return metric_data

def handler(event, context):
    # Retrieve configuration from S3 (get environment variable)
    dashboard_config = loadConfigurations()

    # removes potential duplicates in metrics and SPS queries
    configurations = [
        json.loads(config)
        for config in
        list({json.dumps(config, sort_keys=True, indent=0) for config in list([config for sublist in
              list([configuration['Sps'] for configuration in dashboard_config])
              for config in sublist])})
    ]

    # TODO: Change this simple validation for cerberus schema evaluation
    validation_errors = list(
        filter(lambda x: x is not None,
               [__validateConfiguration(config) for config in configurations]))
    if validation_errors:
        msg = f'Got errors when validating internal elements in configuration : {str(validation_errors)}'
        logger.error(msg)
        raise Exception(msg)

    # For each of the entries in the configuration
    metric_data_results = []
    for configuration in configurations:
        try:
            logger.info(f"About to load scores for {configuration['ConfigurationName']}")
            spot_placement_scores = fetchSPSScore(configuration)
            logger.info(f"About to put scores for {configuration['ConfigurationName']} into cloudwatch")
            metric_data = __putSPSMetricsInCloudwatch(configuration, spot_placement_scores)
            metric_data_results.append(metric_data)
        except Exception as e:
            logger.error(f" Error while processing {configuration['ConfigurationName']}: {e}")
            # We shallow the exception and attempt to continue with the loop
            # raise(e)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "result": metric_data_results
        }),
    }


if __name__ == "__main__":
    handler(None, None)
