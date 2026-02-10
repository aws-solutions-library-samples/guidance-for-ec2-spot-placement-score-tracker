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

import yaml
import os
import boto3

def load_custom_config(custom_path='./configuration/custom_config.yaml'):
    if os.path.exists(custom_path):
        with open(custom_path, 'r') as f:
            return yaml.safe_load(f)
    return {'dashboards': []}

def load_karpenter_config(karpenter_path='./configuration/karpenter_nodepools_config.yaml'):
    if os.path.exists(karpenter_path):
        with open(karpenter_path, 'r') as f:
            return list(yaml.safe_load_all(f))
    return []

def filter_instance_types_by_requirements(requirements):
    import re
    
    ec2_client = boto3.client('ec2')
    instance_type_scheme = re.compile(r'(^[a-z]+)(\-[0-9]+tb)?([0-9]+).*\.')
    
    all_instance_types = []
    
    # Get all instance types with details
    paginator = ec2_client.get_paginator('describe_instance_types')
    for page in paginator.paginate():
        for info in page['InstanceTypes']:
            instance_type = info['InstanceType']
            
            # Extract instance properties based on Karpenter NodePool structure
            properties = {}
            
            # Instance category and generation from regex
            match = instance_type_scheme.match(instance_type + '.')
            if match:
                properties['karpenter.k8s.aws/instance-category'] = match.group(1)
                properties['karpenter.k8s.aws/instance-generation'] = int(match.group(3))
            
            # Instance family and size 
            parts = instance_type.split('.')
            if len(parts) == 2:
                properties['karpenter.k8s.aws/instance-family'] = parts[0]
            
            # CPU count
            properties['karpenter.k8s.aws/instance-cpu'] = str(info['VCpuInfo']['DefaultVCpus'])
            
            # Hypervisor
            properties['karpenter.k8s.aws/instance-hypervisor'] = info.get('Hypervisor', 'xen').lower()
            
            # Architecture
            arch = info['ProcessorInfo']['SupportedArchitectures'][0]
            properties['kubernetes.io/arch'] = 'amd64' if arch == 'x86_64' else arch
            
            # Check if instance matches ALL requirements 
            matches = True
            for req_key, req_spec in requirements.items():
                if req_key in properties:
                    operator = req_spec.get('operator', 'In')
                    values = req_spec.get('values', [])
                    prop_value = properties[req_key]
                    
                    if operator == 'In':
                        if prop_value not in values:
                            matches = False
                            break
                    elif operator == 'Gt':
                        if isinstance(prop_value, int):
                            if prop_value <= int(values[0]):
                                matches = False
                                break
                        else:
                            if int(prop_value) <= int(values[0]):
                                matches = False
                                break
            
            if matches:
                all_instance_types.append(instance_type)
    
    return sorted(all_instance_types)

def convert_karpenter_to_sps_config(nodepool, target_capacity):
    name = nodepool['metadata']['name']
    requirements = nodepool['spec']['template']['spec']['requirements']
    
    # Extract explicit instance types and exclusions
    instance_types = []
    excluded_instance_types = []
    karpenter_requirements = {}
    
    for req in requirements:
        key = req['key']
        values = req['values']
        operator = req.get('operator', 'In')
        
        if key == 'node.kubernetes.io/instance-type':
            if operator == 'In':
                instance_types.extend(values)
            elif operator == 'NotIn':
                excluded_instance_types.extend(values)
        elif key in [
            'karpenter.k8s.aws/instance-category',
            'karpenter.k8s.aws/instance-family', 
            'karpenter.k8s.aws/instance-cpu',
            'karpenter.k8s.aws/instance-hypervisor',
            'karpenter.k8s.aws/instance-generation',
            'kubernetes.io/arch'
        ]:
            karpenter_requirements[key] = {
                'operator': operator,
                'values': values
            }
    
    # Use explicit instance types if specified
    if instance_types:
        # Remove excluded instance types
        if excluded_instance_types:
            instance_types = [it for it in instance_types if it not in excluded_instance_types]
        
        return [{
            'ConfigurationName': name,
            'WorkloadType': 'Karpenter',
            'KarpenterNodepool': name,
            'SingleAvailabilityZone': False,
            'TargetCapacity': target_capacity,
            'TargetCapacityUnitType': 'vcpu',
            'InstanceTypes': instance_types
        }]
    
    # Filter by requirements if specified
    if karpenter_requirements:
        try:
            filtered_instance_types = filter_instance_types_by_requirements(karpenter_requirements)
            # Remove excluded instance types
            if excluded_instance_types:
                filtered_instance_types = [it for it in filtered_instance_types if it not in excluded_instance_types]
            
            if filtered_instance_types:
                return [{
                    'ConfigurationName': name,
                    'WorkloadType': 'Karpenter',
                    'KarpenterNodepool': name,
                    'SingleAvailabilityZone': False,
                    'TargetCapacity': target_capacity,
                    'TargetCapacityUnitType': 'vcpu',
                    'InstanceTypes': filtered_instance_types
                }]
        except Exception as e:
            print(f"Error filtering instance types for {name}: {e}")
            return []
    
    # No valid configuration found
    return []

def generate_unified_config(override_regions=None, override_target_capacity=None, custom_config_path=None, karpenter_config_path=None):
    custom_config = load_custom_config(custom_config_path) if custom_config_path else load_custom_config()
    karpenter_nodepools = load_karpenter_config(karpenter_config_path) if karpenter_config_path else load_karpenter_config()

    regions = override_regions or custom_config.get('default_regions', ['us-east-1', 'eu-west-1'])
    
    unified_config = {
        'default_regions': regions,
        'dashboards': []
    }
    
    for dashboard in custom_config.get('dashboards', []):
        # Add WorkloadType to custom configs
        for sps_config in dashboard['Sps']:
            if 'WorkloadType' not in sps_config:
                sps_config['WorkloadType'] = 'Custom'
        unified_config['dashboards'].append(dashboard)
    
    target_capacity = override_target_capacity or custom_config.get('default_target_capacity', [1000, 5000, 10000])
    
    # Process Karpenter nodepools
    if karpenter_nodepools:
        karpenter_configs = []
        for nodepool in karpenter_nodepools:
            if nodepool and 'metadata' in nodepool and 'spec' in nodepool:
                sps_configs = convert_karpenter_to_sps_config(nodepool, target_capacity)
                # convert_karpenter_to_sps_config now returns a list
                for sps_config in sps_configs:
                    sps_config['RegionNames'] = unified_config['default_regions']
                    karpenter_configs.append(sps_config)
        
        if karpenter_configs:
            unified_config['dashboards'].append({
                'Dashboard': 'Karpenter-Workloads',
                'Sps': karpenter_configs
            })
    
    # Write spot_config.yaml
    spot_config_path = './configuration/spot_config.yaml'
    with open(spot_config_path, 'w') as f:
        yaml.dump(unified_config, f, default_flow_style=False, sort_keys=False)
    
    print(f"Generated configuration: {spot_config_path}")
    print(f"Found {len(custom_config.get('dashboards', []))} custom configurations")
    print(f"Found {len(karpenter_nodepools)} Karpenter nodepools")
    return spot_config_path

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate unified spot configuration')
    parser.add_argument('--regions', type=str, help='Comma-separated AWS regions (e.g., us-east-1,us-west-2)')
    parser.add_argument('--target-capacity', type=str, help='Comma-separated target capacity values (e.g., 1000,5000,10000)')
    parser.add_argument('--custom-config', type=str, help='Path to custom config YAML file')
    parser.add_argument('--karpenter-config', type=str, help='Path to Karpenter config YAML file')
    args = parser.parse_args()
    
    # Parse regions if provided
    override_regions = None
    if args.regions:
        override_regions = [x.strip() for x in args.regions.split(',')]
    
    # Parse target capacity if provided
    override_capacity = None
    if args.target_capacity:
        override_capacity = [int(x.strip()) for x in args.target_capacity.split(',')]
    
    generate_unified_config(override_regions, override_capacity, args.custom_config, args.karpenter_config)