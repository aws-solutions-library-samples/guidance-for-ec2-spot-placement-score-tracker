# Spot Placement Score Tracker
Author: Carlos Manzanedo Rueda <ruecarlo@amazon.com>

## Introduction 
Amazon EC2 Spot Instances let you take advantage of unused EC2 capacity in the AWS cloud. 
Spot Instances are available at up to a 90% discount compared to On-Demand prices. 
Spot Placement Score (SPS) is a feature that helps AWS Spot customers by providing 
recommendations about which are the best suited AWS Region or Availability Zone
to run a diversified configuration that adjusts to the customer requirements.

Spot capacity fluctuates. You can't be sure that you'll always get the capacity that you need.
A Spot placement score indicates how likely it is that a Spot request will succeed
in a Region or Availability Zone. Spot placement score provides a score from 1 to 9 
of how successful your experience when using Spot instances would be on a set of regions.

This project automates the capture of [Spot Placement Scores](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-placement-score.html)
and stores SPS metrics in [CloudWatch](https://aws.amazon.com/cloudwatch/). Historic metrics
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

Spot placement Score considers takes as an input a diversified fleet. With this **Spot Placement
Score Tracker** dashboards, you will be able to monitor and evaluate how to
apply spot best practices and as a result optimize your workload to make the most
of Spare capacity at scale. Some of the best practices you should consider are:
* Increasing Instance Diversification. Adding instances from other sizes, and families. 
* Considering Flexibility in your workloads by selecting multiple Availability zones and
if your workload allows, exploring the possibility of using multiple region
* Considering running at times of the day when spare capacity is more available 

The following graph shows one of the Spot Placement Score dashboards

![img](/docs/spot-placement-score.png)


## Architecture Diagram

The project provides Infrastructure as Code (IaaC) automation using [CDK](https://docs.aws.amazon.com/cdk/latest/guide/home.html)
to deploy the infrastructure, IAM roles and policies required to run Lambda that gets executed
every 5 minutes to collect the Spot Placement Scores of as many diversified configurations
as needed.

![img](/docs/SpotPlacementScore.drawio.png)

The image above shows components deployed using CDK. If you are not familiar with CDK you can use the 
[cloud 9 to proceed with the whole setup and installation here](#steps-to-consider-before-deployment-sps-dashboard-configuration).

The CDK project sets up a few policies and roles to run with least privilege read access to all resources except
for Cloudwach for which it needs to store metrics.

The diagram shows how the different steps are called:

* First, Event Bridge cron functionality starts the execution of the `spotPlacementScoresLambda` every 5 minutes.
* The lambda function, uses the environment variable config to fetch the YAML document that contains the dashboard.
* The lambda decomposes all the requests and starts requesting one by one the queries to SPS
* The responses are then used to create and store CloudWatch Metrics into Cloudwatch.
* The CDK project did also read the YAML document before storing it into S3 and did use the project to
preset the CloudWatch representation of the dashboards.

## Important notes Spot Placement Score Limits imposed by AWS

Spot placement Score API's imposes a set of limits that you should be aware of:
 - Limit on number of Instances, vCPU, Memory for each request. This limit will be 
equivalent to the number of instances that you are already using in your account
in a regular way, so that you can evaluate your current workload on different regions or AZ. 
 - Limit on number of configurations. Spot Placement Score limits you to a few (10) diversified
configurations. If you configure too many configurations you may find that the lambda
will fail and will be limited to just query a few of the configurations. This will also be
checked as part of the CDK deployment process.

The following log snippet shows one of this throttling limits in action:
```bash
botocore.exceptions.ClientError: An error occurred (MaxConfigLimitExceeded) when 
calling the GetSpotPlacementScores operation: You have exceeded your maximum allowed 
Spot placement configurations. You can retry configurations that you used within the 
last 24 hours, or wait for 24 hours before specifying a new configuration.
```

## Steps to consider before Deployment: SPS Dashboard Configuration  

The file [sps_configuration.yaml](sps_configuration/sps_config.yaml) provides an 
example configuration file that you can modify and adapt to your needs. This file will be 
used and deployed by the stack to the cloud and will be kept in S3 as the source configuration. 
The file uses a YAML format that follows a compatible schema as the one used by the Spot Placement 
Score call. You can find more information on the SPS API structure for 
python [here](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.get_spot_placement_scores)

Before proceeding with the deployment of the dashboards CDK you will need to adapt the 
configuration file that defines the different Spot diversified configurations. 

To learn how to better adjust your configurations [keep reading the best practices section](#configuration-best-practices) 
and understand how to get actionable insights based on your configuration that will help you optimize your workload.


## Requirements
* [CDK](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html)
* Python =>3.8
* [virtualenv](https://pypi.org/project/virtualenv/)
* IAM Permissions run CDK stacks and request for Spot Placement Score
* Docker


## Installation

### Deploying CDK project using Cloud9   
The easier way to setup and deploy your environment is using Cloud9 following 
this instructions. 

* Create a Cloud9 environment : 
* On the console run the following commands:

 1.- Create a Cloud9 environment in your account. **Note**: If you use a pre-existing cloud9 environment you may need to
upgrade your python and npm.

 2.- Download by clicking to this link [**EC2 Spot Placement Score Dashboard Tracker- 1.0.0 version from Github**](https://github.com/aws-samples/ec2-spot-placement-score-tracker/archive/refs/tags/v1.0.0.tar.gz)
to your desktop:

 3.- Upload the file [**ec2-spot-placement-score-tracker-1.0.0.tar.gz**](https://github.com/aws-samples/ec2-spot-placement-score-tracker/archive/refs/tags/v1.0.0.tar.gz)
file to your Cloud9 environment. To upload you can just drag and drop the file, into the green folder at the top.

#### Uncompress the application 
Execute the following commands on Cloud 9 (you can just copy and paste)
```
tar xzvf ec2-spot-placement-score-tracker-1.0.0.tar.gz
cd $HOME/environment/ec2-spot-placement-score-tracker-1.0.0
```

#### Configuring the Cloud9 Setup before deployment

At this stage, you can check on the Cloud 9 editor and edit the configuration file
at **$HOME/environment/spot-placement-score-dashboard-cdk-v0.2.0/sps_configuration/sps_config.yaml**
We do provide an example file with a few passwords, but we also recommend checking 
[the best practices below](#dashboard-setup-best-practices). Use those best practices to define
the dashboards that are meaningful for your configuration.


#### Deploy dependencies

Once your configuration file is ready, we should install CDK and the rest of dependencies.
```
npm install -g --force aws-cdk
pip install virtualenv
virtualenv .env
source .env/bin/activate
pip install -r requirements.txt 
```

#### Bootstrap 
Deploying AWS CDK apps into an AWS environment may require that you provision resources
the AWS CDK needs to perform the deployment. These resources include an Amazon S3 
bucket for storing files and IAM roles. We will also use that S3 bucket to upload our dashboard configuration. 
Execute the following command to bootstrap your environment:

```bash
cdk bootstrap
```
You can read more about [the bootstrapping process here](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html)

#### Deploying the application & Dashboards

```bash
cdk deploy
```

Once deployed, go to your AWS console and visit the CloudWatch Dashboard section. The Dashboards are aggregated 
with a period of 15 minutes.


#### Cleanup 

Once you are done, you can destroy the cdk deployment and delete the cloud9 environment.
You can also delete the configuration by deleting the stack in CloudFormation.
```
cdk destroy
```

**Note** the user you run this with, should be able to create Cloud9
environments create deploy CloudFormation stacks, add extra IAM roles 
and have access to execute Spot Placement Score queries.


## Configuration

The configuration file contains a YAML defined vector of dashboards. For example
The following snippet shows how to configure two dashboards for two workloads.
Each dashboard can define `DefaultWidgetHeight` and `DefaultWidgetWidth` to set 
the size of each individual chart. The maximum width of CloudWatch Grid is 24, so
in this example below we will be creating rows of 2 charts of height 12.
The `Sps` section defines a list of SPS configurations to evaluate.


```yaml
- Dashboard: MySpsDashboard-for-Workload-A
  DefaultWidgetHeight: 12    # Default : 6
  DefaultWidgetWidth: 12     # Default : 6, Grid Maximum Width:24
  Sps:
    ...
- Dashboard: MySpsDashboard-for-Workload-B
  DefaultWidgetHeight: 12    # Default : 6
  DefaultWidgetWidth: 12     # Default : 6, Grid Maximum Width:24
  Sps:
    ...
```

Now that we know how to create more than one dashboard, let's check at the SPS section.
The `Sps` section defines an array of SPS configurations. Each individual `Sps` section
has a named SPS query. The request format is the same as the serialised version of the 
call to SPS API's. You can use as a reference the boto documentation [here](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.get_spot_placement_scores)
or the [aws-cli for spot placement score](https://docs.aws.amazon.com/cli/latest/reference/ec2/get-spot-placement-scores.html)
Check the section **JSON Syntax** 

Below  is an example of a Dashboard with a single SPS chart. The configuration shows a 
dashboard for workload A with 2 charts per row. The first chart has a name `Compute Xlarge`
and uses the schemas defined in the link above to diversify over instances *c5.xlarge* and 
similar sized instances from the compute instance family. Aside from the key `ConfigurationName`
the rest of the parameters follows the schemas provided in the links above to target european
regions up to 2000 vCPUs. Note that below the configuration `Compute Xlarge`, there is a second 
one for `Compute 2Xlarge`. 

```yaml
- Dashboard: MySpsDashboard-for-Workload-A
  DefaultWidgetHeight: 12    # Default : 6
  DefaultWidgetWidth: 12     # Default : 6, Grid Maximum Width:24
  Sps:
  # Second configuration this one for Compute 2xlarge
  - ConfigurationName: Compute Xlarge
    InstanceTypes:
    - c5.xlarge
    - c6i.xlarge
    - c5a.xlarge
    - c5d.xlarge
    ...
    RegionNames:
    - eu-west-1
    - eu-west-2
    ...
    SingleAvailabilityZone: False
    TargetCapacity: 2000
    TargetCapacityUnitType: vcpu
    
  # Second configuration this one for Compute 2xlarge
  - ConfigurationName: Compute 2Xlarge
    ...
```

Instead  of using `InstanceTypes` we do recommend using `InstanceRequirementsWithMetadata`. This
maps with requesting Diversification using Instance attributes rather than the AWS instance names.
You can read more about [Attribute Based Instance Selection](https://aws.amazon.com/blogs/aws/new-attribute-based-instance-type-selection-for-ec2-auto-scaling-and-ec2-fleet/)
We do **strongly recommend to define your configurations using Attribute Based Instance Selection**.
By doing that you will have a simple configuration to maximise the diversification and instance types
that your workload can use and that will consider new instances as they are released by AWS. 

```yaml
- Dashboard: MySpsDashboard-for-Workload-A
  DefaultWidgetHeight: 12    # Default : 6
  DefaultWidgetWidth: 12     # Default : 6, Grid Maximum Width:24
  Sps:
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

### Advanced configurations

The configuration file, by default supports the definition of multiple dashboards,
but still in some scenarios you may want to have multiple configuration files,
or deploy multiple times a CloudFormation stack with a different name and a different
configuration. 

#### Creating a stack with a different configuration file

The default configuration file is stored in the `sps_configuration/sps_config.yaml`.
You can point to any other file by using the context key `sps-config` in when launching
cdk commands:
```bash
cdk deploy --context "sps-config=./my_sps_dashboard_configuration.yaml"
```

#### Creating and deploying multiple stacks on the same AWS account

In some situations you may want to deploy a two different configuration files simultaneously on
the same account. You can do it by using the following command 
```bash
cdk deploy --context "sps-config=./my_sps_dashboard_configuration.yaml" --context "stack-name=my-sps-demo" 
```

This will create a new Stack named `my-sps-demo`. To destroy/remove the stack you can use CloudFormation
directly.


## Dashboard Setup Best Practices 

Checking what is the Spot Placement Score is definitely useful. You can use this project and 
[Spot Interruption Dashboard](https://github.com/aws-samples/ec2-spot-interruption-dashboard)
to get understand and get the right observability for your workloads, but that's just the begining.

The goal when we set up SPS dashboard is to find actionable configurations that will help to improve 
the way that our workload provisions Spot capacity at the scale you need. The next steps will guide you
on a set of steps to define your dashboard configuration.

* Consider using a dashboard per workload. We will focus our attention at the workload level and will
evaluate which other configurations can improve our current configurations.

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

* Create the extra configurations in the same dashboard. Make sure the properties for `RegionNames`, 
`SingleAvailabilityZone` and `TargetCapacity` stay the same so you can compare the configurations like for like.

* Adapt the dashboard `DefaultWidgetWidth` to define how many charts/configurations you want per row.
For example if you have 4 configurations, you can set the `DefaultWidgetWidth` to 6 so that each row contains 
the 4 configurations side by side, making them easier to compare.

* With the first row already configured, we will follow the same pattern in the second row. We can make a copy of 
all the configurations, and then change just one dimension. The idea is that we can use the row / column patter to
identify configurations. For example we could chose the `TargetCapacity` dimension, copying all the previous configuration
and then checking what would happen if our workload doubles in size, or if we could perhaps reduce in two and run
two copies in different regions.
