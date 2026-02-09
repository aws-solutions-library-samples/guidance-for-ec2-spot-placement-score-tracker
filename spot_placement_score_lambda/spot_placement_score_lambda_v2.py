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
# Authors: Carlos Manzanedo Rueda <ruecarlo@amazon.com>, Yael Grossman <yaelgr@amazon.com>

import json
import logging
import os
import boto3
import sys
import yaml
from functools import lru_cache

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

# Global variables
REGION_AZ_COUNTS = {}
INSTANCE_PRICES = {}

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
        configuration_path = os.getenv(DEBUG_CONFIG_FILE)
        if configuration_path is not None and os.path.isfile(configuration_path):
            logger.info(f"Debug mode detected, loading configuration from {configuration_path}")
            with open(configuration_path, 'r') as file:
                config_yaml = yaml.load(file.read(), Loader=yaml.loader.SafeLoader)
                return config_yaml

    s3_bucket = os.getenv(S3_CONFIGURATION_BUCKET_ENV_NAME)
    s3_object = os.getenv(S3_CONFIGURATION_OBJECT_KEY)
    
    if not s3_bucket or not s3_object:
        raise Exception(f"Missing environment variables: {S3_CONFIGURATION_BUCKET_ENV_NAME} or {S3_CONFIGURATION_OBJECT_KEY}")

    s3_client = boto3.client('s3')
    response = s3_client.get_object(Bucket=s3_bucket, Key=s3_object)
    
    if response['ResponseMetadata']['HTTPStatusCode'] != 200:
        raise Exception(f"Could not retrieve s3://{s3_bucket}/{s3_object}")

    config_doc = response['Body'].read()
    config_yaml = yaml.load(config_doc, Loader=yaml.loader.SafeLoader)
    return config_yaml

def __validateConfiguration(configuration=None):
    # For the moment I'll leave a pretty dumb  validation function,
    # But in the future this should hold a schema that verifies the configuration
    # Section using schema libraries such as [Cerberus](https://docs.python-cerberus.org/en/stable/)
    if configuration is None:
        return "Configuration does not exist or is malformed"

    missing_fields = []
    for key in ['ConfigurationName', 'TargetCapacity', 'TargetCapacityUnitType',
                'SingleAvailabilityZone', 'RegionNames']:
        if key not in configuration:
            missing_fields.append(key)

    if 'InstanceTypes' not in configuration and 'InstanceRequirementsWithMetadata' not in configuration:
        missing_fields.append('InstanceTypes or InstanceRequirementsWithMetadata')

    return f"Missing fields: {missing_fields}" if missing_fields else None

def getInstanceFromReq(configuration=None):
    # Get list of instance types for ABIS configuration
    ec2_client = boto3.client('ec2')
    response = ec2_client.get_instance_types_from_instance_requirements(
        ArchitectureTypes=configuration['InstanceRequirementsWithMetadata']['ArchitectureTypes'],
        VirtualizationTypes=["hvm"],
        InstanceRequirements=configuration['InstanceRequirementsWithMetadata']['InstanceRequirements']
    )
    return [item['InstanceType'] for item in response['InstanceTypes']]

def getInstanceTypeDetails(instance_types):
    # Get vCPU counts for instance types (batched, skip invalid types). To be used for normalizing price per vcpu
    ec2_client = boto3.client('ec2')
    cpu_counts = {}
    
    # Filter out known invalid instance types upfront
    valid_instance_types = []
    for instance_type in instance_types:
        try:
            ec2_client.describe_instance_types(InstanceTypes=[instance_type])
            valid_instance_types.append(instance_type)
        except Exception:
            logger.warning(f"Skipping invalid instance type: {instance_type}")
    
    # Process valid types in batches of 100
    for i in range(0, len(valid_instance_types), 100):
        batch = valid_instance_types[i:i+100]
        try:
            instance_details = ec2_client.describe_instance_types(InstanceTypes=batch)
            for item in instance_details['InstanceTypes']:
                cpu_counts[item['InstanceType']] = item['VCpuInfo']['DefaultVCpus']
        except Exception as e:
            logger.error(f"Error getting instance details for batch: {e}")
    
    return cpu_counts

@lru_cache(maxsize=20)
def get_az_count(region=None):
    # Get the number of availability zones in a region
    ec2_client = boto3.client('ec2', region_name=region) if region else boto3.client('ec2')
    az_response = ec2_client.describe_availability_zones()
    return len(az_response['AvailabilityZones'])

def prefetch_az_counts(configurations):
    # Fetch AZ counts for all regions
    global REGION_AZ_COUNTS
    all_regions = set(region for config in configurations if 'RegionNames' in config for region in config['RegionNames'])
    REGION_AZ_COUNTS = {region: get_az_count(region) for region in all_regions}
    return REGION_AZ_COUNTS

def describeSpotPriceHistory(instance_type, region=None):
    # Get minimum spot price for instance type in region
    global REGION_AZ_COUNTS, INSTANCE_PRICES
    ec2_client = boto3.client('ec2', region_name=region) if region else boto3.client('ec2')
    
    az_count = REGION_AZ_COUNTS.get(region, get_az_count(region))
    
    response = ec2_client.describe_spot_price_history(
        InstanceTypes=[instance_type],
        ProductDescriptions=['Linux/UNIX'],
        MaxResults=az_count
    )
    
    min_price = None
    if response['SpotPriceHistory']:
        timestamps = sorted(set([item['Timestamp'] for item in response['SpotPriceHistory']]), reverse=True)
        if timestamps:
            latest_timestamp = timestamps[0]
            latest_prices = [float(item['SpotPrice']) for item in response['SpotPriceHistory'] 
                            if item['Timestamp'] == latest_timestamp]
            min_price = min(latest_prices) if latest_prices else None

    return min_price

def prefetch_instance_prices(configurations):
    # Fetch spot prices for all instance types in regions 
    global INSTANCE_PRICES
    
    region_instance_types = {}
    
    for config in configurations:
        if 'RegionNames' not in config:
            continue
        instance_types = []
        if 'InstanceTypes' in config:
            instance_types = config['InstanceTypes']
        elif 'InstanceRequirementsWithMetadata' in config:
            instance_types = getInstanceFromReq(config)
            
        for region in config['RegionNames']:
            if region not in region_instance_types:
                region_instance_types[region] = set()
            region_instance_types[region].update(instance_types)
    
    for region, instance_types in region_instance_types.items():
        try:
            ec2_client = boto3.client('ec2', region_name=region)
            instance_list = list(instance_types)
            
            # Process in batches of 100 (API limit)
            for i in range(0, len(instance_list), 100):
                batch = instance_list[i:i+100]
                logger.info(f"Fetching prices for {len(batch)} instance types in {region} (batch {i//100 + 1})")
                
                response = ec2_client.describe_spot_price_history(
                    InstanceTypes=batch,
                    ProductDescriptions=['Linux/UNIX'],
                    MaxResults=1000
                )
                
                # Group by instance type and get latest price
                for item in response['SpotPriceHistory']:
                    price_key = f"{region}:{item['InstanceType']}"
                    if price_key not in INSTANCE_PRICES:
                        INSTANCE_PRICES[price_key] = float(item['SpotPrice'])
                        
        except Exception as e:
            logger.warning(f"Failed to fetch prices for {region}: {e}")
    
    return INSTANCE_PRICES

def calculateConfigPrice(configuration=None, region=None):
    # Calculate normalized price per vcpu for each config in region
    cpu_counts = getInstanceTypeDetails(configuration['InstanceTypes'])
    
    weighted_sum, total_weight = 0, 0
    for instance_type in configuration['InstanceTypes']:
        price_key = f"{region}:{instance_type}"
        min_price = INSTANCE_PRICES.get(price_key)

        if min_price and instance_type in cpu_counts:
            cpu_count = cpu_counts[instance_type]
            weighted_sum += min_price * cpu_count
            total_weight += cpu_count
    
    return round(weighted_sum / total_weight, 2) if total_weight > 0 else 0

def fetchSPSScore(configuration=None):
    ec2_client = boto3.client('ec2')
    
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
    
    if response['ResponseMetadata']['HTTPStatusCode'] != 200:
        logger.error("Could not retrieve the Spot Placement Score")

    return response['SpotPlacementScores']

def __putMetricsInCloudwatch(configuration, spot_placement_scores=None, region_prices=None):
    if spot_placement_scores is None:
        raise Exception("Spot Placement Scores was None, cannot insert in cloudwatch")

    cloudwatch_client = boto3.client('cloudwatch')
    cloudwatch_metric_name = configuration['ConfigurationName']
    target_capacity = configuration['TargetCapacity']
    unit_type = configuration['TargetCapacityUnitType']

    metric_data = [
        {
            'MetricName': 'Score',
            'Dimensions': [
                {'Name': 'Region', 'Value': f"{score['Region']}"},
                {'Name': 'DiversificationName', 'Value': f"{cloudwatch_metric_name}"},
                {'Name': 'UnitType', 'Value': f"{unit_type}"},
                {'Name': 'TargetCapacity', 'Value': f"{target_capacity}"},
                {'Name': 'MetricType', 'Value': "Score"},
                {'Name': 'WorkloadType', 'Value': configuration.get('WorkloadType', 'Custom')}
            ] + ([{'Name': 'AvailabilityZoneId', 'Value': score['AvailabilityZoneId']}] 
                 if 'AvailabilityZoneId' in score else []),
            'Unit': 'Count',
            'Value': score['Score']
        }
        for score in spot_placement_scores
    ]

    # Add price metrics
    if region_prices:
        for region_price in region_prices:
            metric_data.append({
                'MetricName': 'Price',
                'Dimensions': [
                    {'Name': 'Region', 'Value': region_price['Region']},
                    {'Name': 'DiversificationName', 'Value': f"{cloudwatch_metric_name}"},
                    {'Name': 'MetricType', 'Value': "Price"},
                    {'Name': 'WorkloadType', 'Value': configuration.get('WorkloadType', 'Custom')}
                ],
                'Unit': 'None',
                'Value': round(region_price['Price'], 2)
            })

    response = cloudwatch_client.put_metric_data(
        MetricData=metric_data,
        Namespace=SPS_METRIC_NAMESPACE
    )

    if response['ResponseMetadata']['HTTPStatusCode'] != 200:
        logger.error("Could not store metrics to cloudwatch")
    
    logger.info(f"SPS and Price metrics sent for workload: {cloudwatch_metric_name} (WorkloadType: {configuration.get('WorkloadType', 'Custom')}, TargetCapacity: {target_capacity}, Regions: {len(spot_placement_scores)} SPS scores, {len(region_prices) if region_prices else 0} price metrics)")
    return metric_data

def handler(event, context):
    """Main Lambda handler"""
    dashboard_config = loadConfigurations()

    # Expand TargetCapacity lists and remove duplicates
    expanded_configs = []
    for dashboard in dashboard_config['dashboards']:
        for sps_config in dashboard['Sps']:
            target_capacities = sps_config['TargetCapacity']
            if isinstance(target_capacities, list):
                # Create separate config for each target capacity
                for capacity in target_capacities:
                    expanded_config = sps_config.copy()
                    expanded_config['TargetCapacity'] = int(capacity)
                    expanded_configs.append(expanded_config)
            else:
                # Single value, ensure it's an integer
                expanded_config = sps_config.copy()
                expanded_config['TargetCapacity'] = int(target_capacities)
                expanded_configs.append(expanded_config)
    
    # Remove duplicates
    configurations = [
        json.loads(config)
        for config in
        list({json.dumps(config, sort_keys=True, indent=0) for config in expanded_configs})
    ]
    
    # Pre-fetch data
    global REGION_AZ_COUNTS, INSTANCE_PRICES
    REGION_AZ_COUNTS = prefetch_az_counts(configurations)
    INSTANCE_PRICES = prefetch_instance_prices(configurations)

    # Validate configurations
    validation_errors = list(filter(lambda x: x is not None,
                                   [__validateConfiguration(config) for config in configurations]))
    if validation_errors:
        raise Exception(f'Configuration validation errors: {validation_errors}')

    # Process each configuration
    metric_data_results = []
    for configuration in configurations:
        try:
            logger.info(f"Processing {configuration['ConfigurationName']}")
            
            logger.info(f"Step 1: Fetching SPS scores for {configuration['ConfigurationName']}")
            spot_placement_scores = fetchSPSScore(configuration)
            
            logger.info(f"Step 2: Processing instance requirements for {configuration['ConfigurationName']}")
            if 'InstanceRequirementsWithMetadata' in configuration:
                configuration['InstanceTypes'] = getInstanceFromReq(configuration)

            logger.info(f"Step 3: Calculating prices for {configuration['ConfigurationName']}")
            # Calculate prices for each region
            region_prices = []
            for region in configuration['RegionNames']:
                price = calculateConfigPrice(configuration, region)
                region_prices.append({'Region': region, 'Price': price})

            logger.info(f"Step 4: Putting metrics to CloudWatch for {configuration['ConfigurationName']}")
            metric_data = __putMetricsInCloudwatch(configuration, spot_placement_scores, region_prices)
            metric_data_results.append(metric_data)

        except Exception as e:
            import traceback
            logger.error(f"Error processing {configuration['ConfigurationName']}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")

    return {
        "statusCode": 200,
        "body": json.dumps({"result": metric_data_results})
    }

if __name__ == "__main__":
    handler(None, None)