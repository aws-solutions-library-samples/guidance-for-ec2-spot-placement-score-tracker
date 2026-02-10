
# Guidance for EC2 Spot Placement Score Tracker Dashboard on AWS


## Introduction 
[Amazon EC2 Spot Instances](https://aws.amazon.com/ec2/spot/) let you take advantage of unused EC2 capacity in the AWS cloud. 
Spot Instances are available at up to a 90% discount compared to On-Demand prices. 
[Spot Placement Score (SPS)](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-placement-score.html) is a feature that helps AWS Spot customers by providing 
recommendations about which are the best suited AWS Region or Availability Zone
to run a diversified configuration that adjusts to the customer requirements.

Spot capacity fluctuates. You can't be sure that you'll always get the capacity that you need.
A Spot placement score indicates how likely it is that a Spot request will succeed
in a Region or Availability Zone. Spot placement score provides a score from 1 to 9 
of how successful your experience when using Spot instances would be on a set of regions.

This project automates the capture of [Spot Placement Scores](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-placement-score.html) 
and [Spot prices](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSpotPriceHistory.html)
and stores the metrics in [CloudWatch](https://aws.amazon.com/cloudwatch/). Historic metrics
can be then be visualized using CloudWatch Dashboards. CloudWatch can also be used to trigger
Alarms and automation of events such as moving your workload to a region where capacity is available.

Spot can be used to optimize the scale, cost and execution time of Workloads such as 
Containers (K8s, EKS, ECS, etc), Loosely coupled HPC and high throughput computing (AWS Batch, 
Parallel Cluster), Data & Analytics using Spark, Flink, Presto, CICD, Rendering, and in general 
any workload that is retryable, scalable and stateless. 

Spot instances can be managed through Auto Scaling Groups and EC2 Fleet, and controllers
engines such as [Karpenter](https://karpenter.sh/). If the configuration of your workload
follows Spot best practices, when a Spot instance receives a notification
for termination, Auto Scaling Groups, EMR, Karpenter, etc, will automate the replacement of the 
instance from another Spot pool where there is capacity available. Even better! Allocation strategies
such as [capacity-optimized](https://aws.amazon.com/blogs/aws/capacity-optimized-spot-instance-allocation-in-action-at-mobileye-and-skyscanner/) 
,and [price-capacity-optimized](https://aws.amazon.com/blogs/compute/introducing-price-capacity-optimized-allocation-strategy-for-ec2-spot-instances/)
select the optimal pools to reduce the frequency of interruption and cost for your workload.

Spot placement Scores takes as an input a diversified fleet. With this **Spot Placement
Score Tracker** dashboards, you will be able to monitor and evaluate how to
apply spot best practices and as a result optimize your workload to make the most
of Spare capacity at scale. Some of the best practices you should consider are:
* Increasing Instance Diversification. Adding instances from other sizes, and families. 
* Considering Flexibility in your workloads by selecting multiple Availability zones and
if your workload allows, exploring the possibility of using multiple regions
* Considering running at times of the day when spare capacity is more available 

The following figure shows one of the Spot Placement Score dashboards

![img](/docs/spot-placement-score.png)
_Figure 1. Sample Spot Placement Score dashboard_

## Architecture Diagram

The guidance provides Infrastructure as Code (IaaC) deployment automation using [AWS CDK](https://docs.aws.amazon.com/cdk/latest/guide/home.html)
to provision the infrastructure, IAM roles and policies required to run Lambda serverless function that gets executed
every 5 minutes to collect the Spot Placement Scores of as many diversified configurations
as needed.

![img](/docs/building-a-spot-placement-score-tracker-dashboard-on-aws.png)
_Figure 2. EC2 Spot Instance Score Tracker Reference Architecture_

The Reference Architecture above shows architectural components deployed using AWS CDK. If you are not familiar with AWS CDK you can use the preconfigured
[AWS IDE Toolkit or AWS CloudShell](https://aws.amazon.com/blogs/devops/how-to-migrate-from-aws-cloud9-to-aws-ide-toolkits-or-aws-cloudshell/) environments to proceed with the whole setup and installation, otherwise you can install AWS CDK and run deployment from your computer.

The CDK project sets up a few policies and roles to run with least privilege read access to all resources except
for Cloudwach for which it needs to store metrics.

The diagram shows how the workflow steps are invoked:

* First, during CDK deployment, `workloads_detection.py` processes `custom_config.yaml` and `karpenter_nodepools_config.yaml` to generate a unified `spot_config.yaml` configuration file.
* The generated configuration is uploaded to S3 as part of the CDK deployment.
* EventBridge CRON job triggers the `spotPlacementScoresLambda` every 15 minutes.
* The Lambda function fetches the configuration YAML from S3 using environment variables.
* For each configuration, the Lambda queries the EC2 Spot Placement Score API and retrieves current spot pricing.
* The responses are published as CloudWatch Metrics with dimensions for WorkloadType, DiversificationName, Region, TargetCapacity, and UnitType.
* The CDK project creates a unified CloudWatch dashboard with variables that filter metrics by these dimensions, enabling analysis across different workload types (Custom and Karpenter).


## Cost 
You are responsible for the cost of the AWS services used while running this Guidance. As of February 2026, the cost for running this Guidance with the default settings in the US East (N. Virginia) region is approximately $25.37 per month.

* One Lambda function envoked at 15 minutes interval, using the ARM architecture
* One scheduled EventBridge rule envoked at 15 minutes interval
* One CloudWatch dashboard with 4 widgets 
* Two Custom metrics for each combination of a configuration, a region, and a target capacity. The example configuration files consist of 4 regions, 6 configurations, 2 target capacities. Custom metrics are billed per number of metrics stored and number of PutMetricData API calls according to the [CloudWatch pricing in the region being used](https://aws.amazon.com/cloudwatch/pricing/).
* Amazon S3 bucket stores the lambda code and configuration files

_We recommend creating a [Budget](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html) through [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/) to help manage costs. Prices are subject to change. For full details, refer to the pricing webpage for each AWS service used in this Guidance._

### Sample Cost Table 
The following table provides a sample cost breakdown for deploying this Guidance with the default parameters in the US East (N. Virginia) Region `us-east-1` for one month.

| AWS service  | Dimensions | Cost [USD] |
| ------------------------- | ------------------------- | ------------ |
| Amazon Lambda  | Main processing logic, collect the metrics  | $ 1.00|
| Amazon EventBridge  | Scheduled invocations at 15 minutes interval  | $ 0.00|
| Amazon CloudWatch Metrics Dashboard | A single dashboard  | $ 0.00 |
| Amazon CloudWatch Metrics Custom Metrics | 2 metrics for 48 unique combinations of dimensions  | $ 21.60 |
| Amazon CloudWatch Metrics PutMetricData | ˜276k PutMetricData API Calls  | $ 2.76 |
| Amazon S3 | Stores configuration YAML files | $ 0.01 |
| **Total** | | **$ 25.37/mo**|
* First, Event Bridge CRON job functionality starts the execution of the `spotPlacementScoresLambda` every 5 minutes.
* The lambda function, uses the environment variable config to fetch the YAML document that contains the dashboard.
* The lambda decomposes all the requests and starts requesting one by one the queries to SPS
* The responses are then used to create and store CloudWatch Metrics into Cloudwatch.
* The CDK project also reads the YAML document before storing it into S3 and did use the project to
preset the CloudWatch representation of the dashboards.

## Important notes Spot Placement Score Limits imposed by AWS

[Spot Placement Score API](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-placement-score.html) imposes a set of limits that you should be aware of:
 - Limit on number of Instances, vCPU, Memory for each request. This limit will be 
equivalent to the number of instances that you are already using in your account
in a regular way, so that you can evaluate your current workload on different regions or AZ. 
 - Limit on number of configurations. Spot Placement Score limits you to a few (10) diversified
configurations. If you configure too many configurations you may find that the Lambda invocation 
will fail and will be limited to just query a few of the configurations. This will also be
checked as part of the CDK deployment process.

The following log snippet shows one of this throttling limits in action:
```bash
botocore.exceptions.ClientError: An error occurred (MaxConfigLimitExceeded) when 
calling the GetSpotPlacementScores operation: You have exceeded your maximum allowed 
Spot placement configurations. You can retry configurations that you used within the 
last 24 hours, or wait for 24 hours before specifying a new configuration.
```

## Deployment Pre-requisistes: SPS Dashboard Configuration  

This project supports two configuration schemas:

1. Custom workloads using the [Spot Placement Score API](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-placement-score.html) structure located in [custom_config.yaml](configuration/custom_config.yaml)
2. [Karpenter](https://karpenter.sh/) workloads using the Karpenter NodePool schema located in [karpenter_nodepools_config.yaml](configuration/karpenter_nodepools_config.yaml)

During deployment, the `workloads_detection.py` script processes both configuration files and generates a unified `spot_config.yaml` 
that is uploaded to S3 and used by the Lambda function.

>NOTE: For Karpenter Integration - No EKS cluster access required. This project analyzes Karpenter NodePool configurations to generate Spot Placement Score
metrics. It does not require access to your EKS cluster or a running Karpenter installation. The workloads_detection.py script simply 
parses the NodePool YAML schema to extract instance requirements and generate corresponding SPS configurations.

You can use Karpenter NodePool configurations from self-managed Karpenter installations, EKS Auto Mode managed Karpenter, or any Karpenter 
deployment method. To use an externally hosted configuration file, see the section on Creating a stack with a different configuration file.

### Supported AWS Regions

The services discussed and used in this guidance are available in all AWS regions.

### Configuration Files

**custom_config.yaml**: Define custom workloads using either explicit instance type lists or Attribute-Based Instance Selection (ABIS). This file also contains global settings:
- `default_regions`: AWS regions to monitor (used by all configurations)
- `default_target_capacity`: Target capacity values for SPS queries
- `default_target_capacity_unit_type`: Unit type (vcpu)
This file uses a YAML format that follows a compatible schema as the one used by the Spot Placement 
Score call. You can find more information on the SPS API structure for 
Python [here](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.get_spot_placement_scores)

**karpenter_nodepools_config.yaml**: Define Karpenter NodePool configurations. The script converts NodePool requirements into SPS schema, using the global regions and target capacity from `custom_config.yaml`.
This file follows the [Karpenter NodePool Specification](https://karpenter.sh/docs/concepts/nodepools/)

Before proceeding with the deployment of the Spot Placement dashboards with AWS CDK, you will need to adapt the 
configuration file that defines the different Spot configurations. 

To learn how to better adjust your configurations [please read the best practices section](#dashboard-configuration-best-practices) 
and understand how to get actionable insights based on your configuration that will help you optimize your workload.

### Requirements
* [CDK](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html)
* Python =>3.8
* [virtualenv](https://pypi.org/project/virtualenv/)
* [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html) - AWS SDK for Python
* [PyYAML](https://pyyaml.org/) - YAML parser
* IAM Permissions run CDK stacks and request for Spot Placement Score and EC2 APIs
* Docker

## Deployment

1. First clone the latest version from the main branch:
 
```bash
git clone https://github.com/aws-solutions-library-samples/guidance-for-ec2-spot-placement-score-tracker.git
cd guidance-for-ec2-spot-placement-score-tracker
```

2. At this stage, you can check the configuration files located 
at the folder: **guidance-for-ec2-spot-placement-score-tracker/configuration**
We provide an example file with a few workloads, but we also recommend checking 
[the best configuration practices below](#dashboard-setup-best-practices). Follow those best practices to define
the dashboard that is meaningful for you.

3. Deploy dependencies

Once your configuration file is ready, proceed to install CDK and the rest of dependencies.
```bash
npm install -g --force aws-cdk
pip install virtualenv
virtualenv .env
source .env/bin/activate
pip install -r requirements.txt 
```

4. Bootstrapping 

Deploying AWS CDK apps into an AWS environment may require that you provision resources
that AWS CDK needs to perform the deployment. These resources include an Amazon S3  bucket for storing files and IAM roles. 
We will also use that S3 bucket to upload our dashboard configuration. 
Execute the following command to bootstrap your environment:

```bash
cdk bootstrap
```
You can read more about [the bootstrapping process here](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html)

5. Deploying  Application and Dashboards

```bash
cdk deploy
```

Once deployed, navigate to your AWS console and visit the CloudWatch Dashboard section. The Dashboards are aggregated 
with a period of 15 minutes.

**Note** the AWS user you run this with, should be able to create deploy CloudFormation stacks, add extra IAM roles 
and have access to execute Spot Placement Score queries.

## Configuration

The `custom_config.yaml` file contains a YAML defined vector of workloads. 
The `Sps` section defines an array of SPS configurations. Each individual `Sps` section
has a named SPS query. The request format is the same as the serialised version of the 
call to SPS API's. You can use as a reference the boto documentation [here](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.get_spot_placement_scores)
or the [aws-cli for spot placement score](https://docs.aws.amazon.com/cli/latest/reference/ec2/get-spot-placement-scores.html)
Check the section **JSON Syntax** 

Below is an example configuration that defines multiple workload configurations. All configurations will appear in a single unified 
dashboard with dropdown filters. The configuration uses global settings and YAML anchors to ensure consistency across all workloads.
The example shows two configurations: `Compute Xlarge` and `Compute 2Xlarge`. Both use the global `default_regions` and `default_target_capacity` 
settings defined at the top of the file. Aside from the key `ConfigurationName` the rest of the parameters follows the schemas provided in the 
links above to target european regions up to 2000 vCPUs. 

```yaml
# Global configuration - applies to ALL configurations
default_regions: &default_regions
  - eu-west-1
  - eu-west-2
  - eu-central-1
default_target_capacity: &default_target_capacity [1000, 2000]
default_target_capacity_unit_type: &default_target_capacity_unit_type vcpu

dashboards:
- Dashboard: SpotTracker01 
  Sps:
  - ConfigurationName: Compute Xlarge
    InstanceTypes:
    - c5.xlarge
    - c6i.xlarge
    - c5a.xlarge
    - c5d.xlarge
    SingleAvailabilityZone: False
    RegionNames: *default_regions    
    TargetCapacity: *default_target_capacity
    TargetCapacityUnitType: *default_target_capacity_unit_type
    
  - ConfigurationName: Compute 2Xlarge
    InstanceTypes:
    - c5.2xlarge
    - c6i.2xlarge
    - c5a.2xlarge
    - c5d.2xlarge
    SingleAvailabilityZone: False
    RegionNames: *default_regions    
    TargetCapacity: *default_target_capacity
    TargetCapacityUnitType: *default_target_capacity_unit_type

```

Instead  of using `InstanceTypes` we recommend using `InstanceRequirementsWithMetadata`. This
maps with requesting Diversification using Instance attributes rather than the AWS instance names.
You can read more about [Attribute Based Instance Selection](https://aws.amazon.com/blogs/aws/new-attribute-based-instance-type-selection-for-ec2-auto-scaling-and-ec2-fleet/)
We  **strongly recommend** to define your configurations using Attribute Based Instance Selection.
By doing that you will have a simple configuration to maximise the diversification and instance types
that your workload can use and that will consider new instances as they are released by AWS:

```yaml
  # Second configuration this one for Compute 2xlarge
  - ConfigurationName: Compute Xlarge
    InstanceRequirementsWithMetadata:
      ArchitectureTypes:
      - x86_64
      InstanceRequirements:
        VCpuCount:
          Min: 32
        MemoryMiB:
          Min: 256
        AcceleratorCount:
          Max: 0
        BareMetal: excluded
        BurstablePerformance: excluded
        CpuManufacturers:
        - intel
        - amd
        InstanceGenerations:
        - current
        MemoryGiBPerVCpu:
          Min: 8
        SpotMaxPricePercentageOverLowestPrice: 50
    
  # Second configuration this one for Compute 2xlarge
  - ConfigurationName: Compute 2Xlarge
    ...
```

### Advanced deployment configurations

In some scenarios you may want to deploy a CloudFormation stack multiple times with a different name and a different
configuration. 

1. Creating a stack with a different configuration file

The default configuration files are stored in the `configuration/custom_config.yaml` and `configuration/karpenter_nodepools_config.yaml`
You can point to any other file by using the context key `custom-config` or `karpenter-config` in when launching
cdk commands:
```bash
cdk deploy --context custom-config=./my-custom-config.yaml
```
2. Creating and deploying multiple stacks on the same AWS account

In some situations you may want to deploy a two different configuration files simultaneously on
the same account. You can do it by using the following command 
```bash
cdk deploy --context "custom-config=./my_sps_dashboard_configuration.yaml" --context "stack-name=my-sps-demo" 
```

This will create a new Stack named `my-sps-demo`. To destroy/remove the stack you can use CloudFormation
directly.

### Dashboard Configuration Best Practices 

Checking out what is the Spot Placement Score is definitely useful. You can use this project and 
[Spot Interruption Dashboard](https://github.com/aws-samples/ec2-spot-interruption-dashboard)
to get an understanding and get the right observability for your workloads, but that's just the begining.

The goal when we set up SPS dashboard is to find actionable configurations that will help to improve 
the way that our workload provisions Spot capacity at the scale you need. The next steps will guide you
on a set of steps to define your dashboard configuration.

* Understand your workload requirements and find: (a) how many vCPUs you will need, (b) what is the minimum
configuration that qualifies for your workload (c) can the workload be spread across AZ's ? (d) Which 
regions can your organization use, and which ones are you considering using in the future. Set the first
configuration of the dashboard to be your current workload configuration defined in this step.

* Decide which other configurations you'd like to compare your current one against and how that will 
increase diversification. Select up to 3 Configurations from the ones you think have more chances to increase
your access to spare capacity. 3 or 4 is enough adding more configurations can make an analysis confusing (
and you can try others later). 

* To consider new configuration you can use a mix of these techniques such as: 
(a)using Attribute Instance Selection instead of a list of instances (b) Think of using instances of 
larger sizes, or smaller sizes if appropriate for your workload (c) Consider expanding over all Availability
zones if you have not done it yet (and is appropriate for your workload)

* Consider adding potential regions where your workload could run in the future. Think capacity pools may have 
seasonality, which you can use to run your time flexible workload at a different time, find the next 
region to expand on, or find where you'd run your Disaster Recovery regional workload copy.

* With the first row already configured, we will follow the same pattern in the second row. We can make a copy of 
all the configurations, and then change just one dimension. The idea is that we can use the row / column pattern to
identify configurations. For example we could chose the `CpuManufacturers` dimension, copying all the previous configuration
and then checking what would happen if our workload supports other CPUs.

### Using Spot placement scores with Accelerated Compute platforms 

Spot instances are an excellent compute option for short-term, spiky, and flexible AI/ML workloads. Spot Placement Score 
helps you identify regional availability for GPU, AWS Trainium, and AWS Inferentia accelerators at any given time.
If your AI/ML workload requires specific accelerators but are region flexibility, use Spot Placement Score to assess 
capacity availability across regions and deploy to the optimal location based on real-time capacity fluctuations.

* For most instance families: Include at least 3 different instance types in your configuration to maximize diversification.
* For P-family instances (P4, P5, P6): Single instance type configurations are supported.

Below is a sample configuration file for multiple instances in the `P` family:

```yaml
  # Second configuration this one for Compute 2xlarge
  - ConfigurationName: H100/200
    InstanceTypes:
    - p5en.48xlarge
    - p5e.48xlarge
    - p5.48xlarge
    SingleAvailabilityZone: False
    
  # Second configuration this one for Compute 2xlarge
  - ConfigurationName: B200
    ...
```
## Cleanup
Once you are done using this guidance, you can destroy the CDK deployment and delete the deployment environment.
You can use this command or delete the configuration by deleting the stack in CloudFormation.

```bash
cdk destroy
```

## Authors:  
Carlos Manzanedo Rueda, AWS <ruecarlo@amazon.com>  
Daniel Zilberman, AWS <dzilberm@amazon.com>   
Yael Grossman, AWS <yaelgr@amazon.com>  

