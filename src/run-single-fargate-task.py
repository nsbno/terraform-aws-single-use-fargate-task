import json
import boto3
import re
import os
import subprocess
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
    if event["cmd_to_run"]:
        with open("/tmp/cmd_to_run.sh", "w") as f:
            f.write(event["cmd_to_run"])
        try:
            subprocess.check_call("sh -n /tmp/cmd_to_run.sh", shell=True)
        except subprocess.CalledProcessError:
            raise ValueError(
                "'cmd_to_run' does not contain a valid shell command"
            )


def lambda_handler(event, context):
    logger.info("event: " + json.dumps(event))
    region = os.environ["AWS_REGION"]
    padded_event = pad_event(event.copy())
    verify_inputs(padded_event)
    task_family_prefix = (
        "_".join(
            filter(
                None,
                [padded_event["state_machine_id"], padded_event["state"]],
            )
        )
        or "one-off-task"
    )
    task_cpu = padded_event.get("task_cpu", "256")
    task_memory = padded_event.get("task_memory", "512")
    task_family_prefix = re.sub("[^A-Za-z0-9_-]", "_", task_family_prefix)
    task_name = "single-use-tasks"
    task_definition = create_task_definition(
        task_name,
        region,
        task_family_prefix,
        padded_event["image"],
        padded_event["cmd_to_run"],
        padded_event["task_role_arn"],
        padded_event["task_execution_role_arn"],
        task_cpu,
        task_memory
    )
    logger.info(task_definition)
    run_task(
        task_name,
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
        "state_machine_id",
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
    task_family_prefix,
    image_url,
    cmd_to_run,
    task_role_arn,
    task_execution_role_arn,
    task_cpu,
    task_memory
):
    date_time_obj = datetime.now()
    client = boto3.client("ecs")
    task_family = (
        f"{task_family_prefix}-{date_time_obj.strftime('%Y%m%d%H%M%S%f')[:-3]}"
    )
    error_log_command = get_error_log_command(
        "/tmp/workspace/error_header_main.log",
        task_name,
        task_family + "-main",
        region,
    )
    shellscript = f"""
        {{
        (
        set -eu
        {error_log_command}
        sidecar_init() {{
            while [ ! -f /tmp/workspace/init_complete ]; do
                sleep 1
            done
        }}
        sidecar_init
        rm /tmp/workspace/init_complete
        cd /tmp/workspace/entrypoint
        ( set +u; {cmd_to_run or 'true'} )
        )
        echo $? > /tmp/workspace/main-complete
        }} 2>&1 | tee /tmp/workspace/main.log
    """
    # Strip leading whitespace to avoid syntax errors due to heredoc indentation
    shellscript = "\n".join(
        [line.lstrip() for line in shellscript.split("\n")]
    )
    command_str = f"echo '{shellscript}' > script.sh && chmod +x script.sh && ./script.sh"
    logger.info("main command str: " + json.dumps(command_str))
    response = client.register_task_definition(
        family=task_family,
        taskRoleArn=task_role_arn,
        executionRoleArn=task_execution_role_arn,
        networkMode="awsvpc",
        cpu=task_cpu,
        memory=task_memory,
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
    return response["taskDefinition"]


def run_task(
    task_name, task_definition, region, content, token, subnets, ecs_cluster
):
    logger.info("subnets: " + str(subnets))
    client = boto3.client("ecs")
    command_str = prepare_cmd(
        content, token, task_name, task_definition["family"], region,
    )
    logger.info("sidecar command str: " + json.dumps(command_str))
    response = client.run_task(
        cluster=ecs_cluster,
        launchType="FARGATE",
        taskDefinition=f"{task_definition['family']}:{task_definition['revision']}",
        count=1,
        platformVersion="LATEST",
        overrides={
            "containerOverrides": [
                {
                    "name": f"{task_name}-activity-sidecar",
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


def get_error_log_command(filename, task_name, stream_prefix, region):
    """Return a shell command for generating a file containing the header of an error log"""
    error_log_command = f"""
        cat <<EOF > {filename}
        ---------------
        THE FOLLOWING IS JUST AN EXCERPT - FULL LOG AVAILABLE AT:

        https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logStream:group=/aws/ecs/{task_name};prefix={stream_prefix};streamFilter=typeLogStreamPrefix
        ---------------

        EOF
    """
    return error_log_command


def prepare_cmd(content, token, task_name, task_family, region):
    error_log_command = get_error_log_command(
        "/tmp/workspace/error_header_sidecar.log",
        task_name,
        task_family + "-sidecar",
        region,
    )
    command_head = f"""
        mkdir -p /tmp/workspace/entrypoint
        await_main_complete() {{
            while [ ! -f /tmp/workspace/main-complete ]; do
                sleep 1
            done
        }}
    """
    if content == "":
        command_content = ""
    else:
        zip_file = re.findall(r"[^/]*\.zip", content, flags=re.IGNORECASE)[0]
        command_content = f"""
            aws s3 cp {content} /tmp/workspace/
            unzip /tmp/workspace/{zip_file} -d /tmp/workspace/entrypoint
        """
    command_sidecar_failure = ""
    if token == "":
        command_activity_stop = ""
    else:
        # The `--cause` parameter for `send-task-failure` has a limit of 32768 characters
        command_activity_stop = f"""
            result="$(cat /tmp/workspace/main-complete)"
            if [ "$result" -eq 0 ]; then
                aws stepfunctions send-task-success --task-token "{token}" --task-output '{{"output": "$result"}}' --region "{region}"
            else
                aws stepfunctions send-task-failure --task-token "{token}" --error "NonZeroExitCode" --cause "$(cat /tmp/workspace/error_header_main.log; cat /tmp/workspace/main.log | tail -c 32000 | tail -15)"
            fi
        """
        command_sidecar_failure = f"""
            if [ ! "$(cat /tmp/workspace/sidecar_exit_status)" -eq 0 ]; then
                retries=0
                while [ "$retries" -lt 5 ]; do
                    aws stepfunctions send-task-failure --task-token "{token}" --error "NonZeroExitCode" --cause "$(cat /tmp/workspace/error_header_sidecar.log; cat /tmp/workspace/sidecar.log | tail -c 32000 | tail -15)" && break
                    retries="$((retries+1))"
                    echo "Failed to report sidecar failure"
                done
            fi
        """

    command_init_complete = "touch /tmp/workspace/init_complete"
    command_wait = """
        await_main_complete
        echo "main exited with status code $(cat /tmp/workspace/main-complete)"
    """

    command_str = f"""
        {{
        (
        set -eu
        {error_log_command}
        {command_head}
        {command_content}
        {command_init_complete}
        {command_wait}
        {command_activity_stop}
        )
        echo $? > /tmp/workspace/sidecar_exit_status
        }} 2>&1 | tee /tmp/workspace/sidecar.log
        {command_sidecar_failure}
    """
    # Strip leading whitespace to avoid syntax errors due to heredoc indentation
    command_str = "\n".join(
        [line.lstrip() for line in command_str.split("\n")]
    )
    return command_str


def clean_up(task_definition):
    client = boto3.client("ecs")
    response = client.deregister_task_definition(
        taskDefinition=f"{task_definition['family']}:{task_definition['revision']}",
    )

