import json
import boto3
import re
from datetime import datetime
import logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    logger.info ("event: "+ json.dumps(event))
    task_definition = create_task_definition('single-use-tasks', event['image'],event['file_to_run'],event['task_role_arn'],event['task_execution_role_arn'])
    logger.info(task_definition)
    run_task(task_definition,event['content'],event['activity_arn'],event['subnets'],event['ecs_cluster'])
    clean_up(task_definition)


def create_task_definition(task_name, image_url,file_to_run,task_role_arn, task_execution_role_arn):
    current_account_id = boto3.client('sts').get_caller_identity().get('Account')
    date_time_obj = datetime.now()
    client = boto3.client('ecs')
    task_family = 'one-off-task-' + date_time_obj.strftime("%Y%m%d%H%M")
    command_str = (
        "function sidecar_init() { "
            "while [ ! -f /tmp/workspace/init_complete ]; do "
              "sleep 1; "
            "done "
        "} && "
        "sidecar_init && "
        "rm /tmp/workspace/init_complete && "
        "UNZIPPED_FOLDER=`ls -d /tmp/workspace/*/` && "
        "cd /tmp/workspace/ && "
        "" + file_to_run + " && "
        "touch /tmp/workspace/main-complete"
    )
    logger.info("main command str: " + command_str)
    response = client.register_task_definition(
        family=task_family,
        taskRoleArn=task_role_arn,
        executionRoleArn=task_execution_role_arn,
        networkMode='awsvpc',
        cpu='256',
        memory='512',
        volumes=[
            {
                'name': 'workspace',
                'host': {}
            }
        ],
        requiresCompatibilities=[
            'FARGATE'
        ],
        containerDefinitions=[
            {
                'name': task_name,
                'image': image_url,
                'entryPoint': [
                    '/bin/sh',
                    '-c'
                ],
                'command': [ command_str ],
                'essential': False,
                'logConfiguration': {
                    'logDriver': 'awslogs',
                    'options': {
                        'awslogs-create-group': 'true',
                        'awslogs-group': '/aws/ecs/' + task_name,
                        'awslogs-region': 'eu-west-1',
                        'awslogs-stream-prefix': task_family+'-main'
                    }
                },
                'mountPoints': [
                    {
                        'sourceVolume': 'workspace',
                        'containerPath': '/tmp/workspace'
                    }
                ]
            },
            {
                'name': 'stepfunction-activity-sidecar',
                'image': 'vydev/awscli:latest',
                'entryPoint': [
                    '/bin/sh',
                    '-c'
                ],
                'mountPoints': [
                    {
                        'sourceVolume': 'workspace',
                        'containerPath': '/tmp/workspace'
                    }
                ],
                'essential': True,
                'logConfiguration': {
                    'logDriver': 'awslogs',
                    'options': {
                        'awslogs-create-group': 'true',
                        'awslogs-group': '/aws/ecs/' + task_name,
                        'awslogs-region': 'eu-west-1',
                        'awslogs-stream-prefix': task_family+'-sidecar'
                    }
                },
            }
        ]
    )
    return response['taskDefinition']['family'] + ":" + str(response['taskDefinition']['revision'])


def run_task(task_definition, content, activity_arn, subnets,ecs_cluster):
    logger.info("subnets: " + str(subnets))
    client = boto3.client('ecs')
    command_str = (
        "function await_main_complete() { "
          "while [ ! -f /tmp/workspace/main-complete ]; do "
            "sleep 1; "
          "done } && "
        "aws s3 cp "+content+" /tmp/workspace/ && "
        "unzip /tmp/workspace/"+re.findall(r"[^/]*\.zip",content)[0]+" -d /tmp/workspace/ && "
        "touch /tmp/workspace/init_complete && "
        "TASK_TOKEN=`aws stepfunctions get-activity-task --activity-arn "+activity_arn+" --region eu-west-1 | jq -r .'taskToken'` && "
        "await_main_complete  && "
        "echo 'main complete' && "
        "aws stepfunctions send-task-success --task-token $TASK_TOKEN --task-output '{\"output\": \"0\"}' --region eu-west-1"
    )
    logger.info("sidecar command str: " + command_str)
    response = client.run_task(
        cluster=ecs_cluster,
        launchType='FARGATE',
        taskDefinition=task_definition,
        count=1,
        platformVersion='LATEST',
        overrides={
            'containerOverrides': [
                {
                    'name': 'stepfunction-activity-sidecar',
                    'command': [ command_str ]
                }
            ]
        },
        networkConfiguration={
            'awsvpcConfiguration': {
                'subnets': subnets,
                'assignPublicIp': 'ENABLED'
            }
        }
    )

def clean_up(task_definition):
    client = boto3.client('ecs')
    response = client.deregister_task_definition(taskDefinition=task_definition)
