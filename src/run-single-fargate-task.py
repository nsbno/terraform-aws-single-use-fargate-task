import json
import boto3
import re
import os
from datetime import datetime
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def verify_inputs(event):
    if event["content"]:
        if not event["content"].lower().endswith(".zip"):
            logger.error("Expected '%s' to be a zip file", event["content"])
            raise ValueError(
                f'Expected \'{event["content"]}\' to be a zip file'
            )


def lambda_handler(event, context):
    logger.info("event: " + json.dumps(event))
    region = os.environ["AWS_REGION"]
    padded_event = pad_event(event.copy())
    verify_inputs(padded_event)
    task_definition = create_task_definition(
        "single-use-tasks",
        region,
        padded_event["state"],
        padded_event["image"],
        padded_event["cmd_to_run"],
        padded_event["task_role_arn"],
        padded_event["task_execution_role_arn"],
    )
    logger.info(task_definition)
    run_task(
        task_definition,
        region,
        padded_event["content"],
        padded_event["token"],
        padded_event["subnets"],
        padded_event["ecs_cluster"],
    )
    clean_up(task_definition)


def pad_event(eventcopy):
    padded_event = eventcopy
    expected_keys = [
        "content",
        "cmd_to_run",
        "ecs_cluster",
        "image",
        "subnets",
        "state",
        "task_role_arn",
        "task_execution_role_arn",
        "token",
    ]
    for key in expected_keys:
        if not key in eventcopy:
            padded_event[key] = ""
    return padded_event


def create_task_definition(
    task_name,
    region,
    state,
    image_url,
    cmd_to_run,
    task_role_arn,
    task_execution_role_arn,
):
    date_time_obj = datetime.now()
    client = boto3.client("ecs")
    task_family_prefix = (
        re.sub("[^A-Za-z0-9-_]+", "_", state) if state else "one-off-task"
    )
    task_family = (
        f"{task_family_prefix}-{date_time_obj.strftime('%Y%m%d%H%M')}"
    )
    shellscript = (
        "cat <<EOF >> /tmp/workspace/error_header.log\n"
        "---------------\n"
        "THE FOLLOWING IS JUST AN EXCERPT - FULL LOG AVAILABLE AT:\n"
        "\n"
        f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logStream:group=/aws/ecs/{task_name};prefix={task_family}-main;streamFilter=typeLogStreamPrefix\n"
        "---------------\n"
        "\n"
        "EOF\n"
        "(\n"
        "function sidecar_init() { \n"
        "    while [ ! -f /tmp/workspace/init_complete ]; do \n"
        "        sleep 1; \n"
        "    done \n"
        "}\n"
        "sidecar_init \n"
        "rm /tmp/workspace/init_complete \n"
        "cd /tmp/workspace/ \n"
        "" + cmd_to_run + "\n"
        "echo $? > /tmp/workspace/main-complete"
        ") 2>&1 | tee /tmp/workspace/main.log\n"
    )
    command_str = (
        "echo '"
        + shellscript
        + "' > script.sh && chmod +x script.sh && ./script.sh"
    )
    logger.info("main command str: " + command_str)
    response = client.register_task_definition(
        family=task_family,
        taskRoleArn=task_role_arn,
        executionRoleArn=task_execution_role_arn,
        networkMode="awsvpc",
        cpu="256",
        memory="512",
        volumes=[{"name": "workspace", "host": {}}],
        requiresCompatibilities=["FARGATE"],
        containerDefinitions=[
            {
                "name": task_name,
                "image": image_url,
                "entryPoint": ["/bin/sh", "-c"],
                "command": [command_str],
                "essential": False,
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-create-group": "true",
                        "awslogs-group": "/aws/ecs/" + task_name,
                        "awslogs-region": region,
                        "awslogs-stream-prefix": task_family + "-main",
                    },
                },
                "mountPoints": [
                    {
                        "sourceVolume": "workspace",
                        "containerPath": "/tmp/workspace",
                    }
                ],
            },
            {
                "name": task_name + "-activity-sidecar",
                "image": "vydev/awscli:latest",
                "entryPoint": ["/bin/sh", "-c"],
                "mountPoints": [
                    {
                        "sourceVolume": "workspace",
                        "containerPath": "/tmp/workspace",
                    }
                ],
                "essential": True,
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-create-group": "true",
                        "awslogs-group": "/aws/ecs/" + task_name,
                        "awslogs-region": region,
                        "awslogs-stream-prefix": task_family + "-sidecar",
                    },
                },
            },
        ],
    )
    return (
        response["taskDefinition"]["family"]
        + ":"
        + str(response["taskDefinition"]["revision"])
    )


def run_task(task_definition, region, content, token, subnets, ecs_cluster):
    logger.info("subnets: " + str(subnets))
    client = boto3.client("ecs")
    command_str = prepare_cmd(content, token, region)
    logger.info("sidecar command str: " + command_str)
    response = client.run_task(
        cluster=ecs_cluster,
        launchType="FARGATE",
        taskDefinition=task_definition,
        count=1,
        platformVersion="LATEST",
        overrides={
            "containerOverrides": [
                {
                    "name": "single-use-tasks-activity-sidecar",
                    "command": [command_str],
                }
            ]
        },
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subnets,
                "assignPublicIp": "ENABLED",
            }
        },
    )


def prepare_cmd(content, token, region):
    command_head = (
        "function await_main_complete() { "
        "while [ ! -f /tmp/workspace/main-complete ]; do "
        "sleep 1; "
        "done } && "
    )
    if content == "":
        command_content = ""
    else:
        command_content = (
            "{ aws s3 cp " + content + " /tmp/workspace/ && "
            "unzip /tmp/workspace/"
            + re.findall(r"[^/]*\.zip", content, flags=re.IGNORECASE)[0]
            + ' -d /tmp/workspace/; echo $? > /tmp/workspace/mount_complete; } 2>&1 | tee /tmp/workspace/sidecar.log && test "$(cat /tmp/workspace/mount_complete)" = 0 || '
            + "{ aws stepfunctions send-task-failure --task-token "
            + f'"{token}"'
            + f' --error "NonZeroExitCode" --cause "$(cat /tmp/workspace/sidecar.log && echo && echo "Does the file \'{content}\' exist, and does the container have permissions to access it?" | tail -c 32768)"; return 1; }} && '
        )
    if token == "":
        command_activity_stop = ""
    else:
        # The `--cause` parameter for `send-task-failure` has a limit of 32768 characters
        command_activity_stop = (
            "&& result=$(cat /tmp/workspace/main-complete) && if [ $result = 0 ]; then aws stepfunctions send-task-success --task-token "
            + token
            + ' --task-output \'{"output": "$result"}\' --region '
            + region
            + "; else aws stepfunctions send-task-failure --task-token "
            + token
            + ' --error "NonZeroExitCode" --cause "$(cat /tmp/workspace/error_header.log; cat /tmp/workspace/main.log | tail -c 32000 | tail -15)"'
            + "; fi"
        )

    command_init_complete = "touch /tmp/workspace/init_complete && "
    command_wait = (
        "await_main_complete  && "
        'echo "main complete $(cat tmp/workspace/main-complete)"'
    )

    command_str = (
        command_head
        + command_content
        + command_init_complete
        + command_wait
        + command_activity_stop
    )
    return command_str


def clean_up(task_definition):
    client = boto3.client("ecs")
    response = client.deregister_task_definition(
        taskDefinition=task_definition
    )

