import json
import boto3
import re
import os
import subprocess
from datetime import datetime
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Global variables to simplify code
WORKSPACE = "/tmp/workspace"
MAIN_CONTAINER_FOLDER = f"{WORKSPACE}/main-container"
SIDECAR_CONTAINER_FOLDER = f"{WORKSPACE}/sidecar-container"
ENTRYPOINT_FOLDER = f"{WORKSPACE}/entrypoint"

SIDECAR_LOG_GROUP_NAME = os.environ["SIDECAR_LOG_GROUP_NAME"]
MAIN_LOG_GROUP_NAME = os.environ["MAIN_LOG_GROUP_NAME"]


def verify_inputs(event):
    required_keys = [
        "ecs_cluster",
        "image",
        "subnets",
        "task_execution_role_arn",
    ]
    if not all(key in event for key in required_keys):
        raise ValueError(
            "Missing one or more required keys: %s", required_keys
        )
    if event["content"] and event["mountpoints"]:
        raise ValueError(
            "The arguments 'content' and 'mountpoints' are mutually exclusive."
        )
    if event["content"]:
        if not event["content"].lower().endswith(".zip"):
            raise ValueError(f"Expected '{event['content']}' to be a zip file")
    if event["mountpoints"]:
        for name, content in event["mountpoints"].items():
            if not content.lower().endswith(".zip"):
                raise ValueError(
                    f"Expected content '{content}' of mountpoint '{name}' to be a zip file"
                )
    if not isinstance(event["task_cpu"], str) or not isinstance(
        event["task_memory"], str
    ):
        raise ValueError("Task CPU and task memory need to be strings")

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
    padded_event = set_defaults(event)
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
    mountpoints = padded_event["mountpoints"] or (
        {"content": padded_event["content"]} if padded_event["content"] else {}
    )
    entrypoint = (
        f"{ENTRYPOINT_FOLDER}/{list(mountpoints.keys())[0]}"
        if len(mountpoints) == 1
        else ENTRYPOINT_FOLDER
    )

    task_family_prefix = re.sub("[^A-Za-z0-9_-]", "_", task_family_prefix)
    task_definition = create_task_definition(
        region,
        task_family_prefix,
        padded_event["image"],
        padded_event["cmd_to_run"],
        padded_event["task_role_arn"],
        padded_event["task_execution_role_arn"],
        entrypoint,
        padded_event["task_cpu"],
        padded_event["task_memory"],
        padded_event["credentials_secret_arn"],
    )
    logger.info(task_definition)
    run_task(
        task_definition,
        region,
        mountpoints,
        padded_event["token"],
        padded_event["subnets"],
        padded_event["ecs_cluster"],
        padded_event["assign_public_ip"],
        padded_event["security_groups"],
    )
    clean_up(task_definition)


def set_defaults(event):
    """Set default values for optional arguments"""
    defaults = {
        "content": "",
        "security_groups": [],
        "assign_public_ip": True,
        "cmd_to_run": "",
        "image": "",
        "task_role_arn": "",
        "mountpoints": {},
        "state": "",
        "task_memory": "512",
        "task_cpu": "256",
        "state_machine_id": "",
        "token": "",
        "credentials_secret_arn": "",
    }
    return {**defaults, **event}


def create_task_definition(
    region,
    task_family_prefix,
    image_url,
    cmd_to_run,
    task_role_arn,
    task_execution_role_arn,
    entrypoint,
    task_cpu,
    task_memory,
    credentials_secret_arn,
    main_log_group_name=MAIN_LOG_GROUP_NAME,
    sidecar_log_group_name=SIDECAR_LOG_GROUP_NAME,
):
    date_time_obj = datetime.now()
    client = boto3.client("ecs")
    task_family = (
        f"{task_family_prefix}-{date_time_obj.strftime('%Y%m%d%H%M%S%f')[:-3]}"
    )
    error_log_command = get_error_log_command(
        f"{MAIN_CONTAINER_FOLDER}/error_header.log",
        main_log_group_name,
        task_family,
        region,
    )
    shellscript = f"""
        sidecar_preinit() {{
            while [ ! -f {SIDECAR_CONTAINER_FOLDER}/preinit-complete ]; do
                sleep 1
            done
        }}
        sidecar_init() {{
            while [ ! -f {SIDECAR_CONTAINER_FOLDER}/init-complete ]; do
                sleep 1
            done
        }}
        sidecar_preinit
        {{
        (
        set -eu
        {error_log_command}
        sidecar_init
        cd {entrypoint}
        ( set +u; {cmd_to_run or 'true'} )
        )
        echo $? > {MAIN_CONTAINER_FOLDER}/complete
        }} 2>&1 | tee {MAIN_CONTAINER_FOLDER}/main.log
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
                "name": "main",
                "image": image_url,
                "entryPoint": ["/bin/sh", "-c"],
                "command": [command_str],
                "essential": False,
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": main_log_group_name,
                        "awslogs-region": region,
                        "awslogs-stream-prefix": task_family,
                    },
                },
                "mountPoints": [
                    {
                        "sourceVolume": "workspace",
                        "containerPath": WORKSPACE,
                    }
                ],
                **(
                    {
                        "repositoryCredentials": {
                            "credentialsParameter": credentials_secret_arn
                        }
                    }
                    if credentials_secret_arn
                    else {}
                ),
            },
            {
                "name": "sidecar",
                "image": "vydev/awscli:latest",
                "entryPoint": ["/bin/sh", "-c"],
                "mountPoints": [
                    {
                        "sourceVolume": "workspace",
                        "containerPath": WORKSPACE,
                    }
                ],
                "essential": True,
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": sidecar_log_group_name,
                        "awslogs-region": region,
                        "awslogs-stream-prefix": task_family,
                    },
                },
                **(
                    {
                        "repositoryCredentials": {
                            "credentialsParameter": credentials_secret_arn
                        }
                    }
                    if credentials_secret_arn
                    else {}
                ),
            },
        ],
    )
    return response["taskDefinition"]


def run_task(
    task_definition,
    region,
    mountpoints,
    token,
    subnets,
    ecs_cluster,
    assign_public_ip,
    security_groups,
    sidecar_log_group_name=SIDECAR_LOG_GROUP_NAME,
):
    logger.info("subnets: " + str(subnets))
    client = boto3.client("ecs")
    command_str = prepare_sidecar_cmd(
        mountpoints,
        token,
        sidecar_log_group_name,
        task_definition["family"],
        region,
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
                    "name": "sidecar",
                    "command": [command_str],
                }
            ]
        },
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subnets,
                **(
                    {"securityGroups": security_groups}
                    if len(security_groups)
                    else {}
                ),
                "assignPublicIp": "ENABLED"
                if assign_public_ip
                else "DISABLED",
            }
        },
    )


def get_error_log_command(filename, log_group_name, log_stream_prefix, region):
    """Return a shell command for generating a file containing the header of an error log"""
    error_log_command = f"""
        cat <<EOF > {filename}
        ---------------
        THE FOLLOWING IS JUST AN EXCERPT - FULL LOG AVAILABLE AT:

        https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logStream:group={log_group_name};prefix={log_stream_prefix};streamFilter=typeLogStreamPrefix
        ---------------

        EOF
    """
    return error_log_command


def prepare_sidecar_cmd(
    mountpoints, token, log_group_name, log_stream_prefix, region
):
    error_log_command = get_error_log_command(
        f"{SIDECAR_CONTAINER_FOLDER}/error_header.log",
        log_group_name,
        log_stream_prefix,
        region,
    )
    command_head = f"""
        mkdir -m +t -p {MAIN_CONTAINER_FOLDER}
        mkdir -p {ENTRYPOINT_FOLDER}
        await_main_complete() {{
            while [ ! -f {MAIN_CONTAINER_FOLDER}/complete ]; do
                sleep 1
            done
        }}
        touch {SIDECAR_CONTAINER_FOLDER}/preinit-complete
    """
    command_content = ""
    for name, content in mountpoints.items():
        zip_file = re.findall(r"[^/]*\.zip", content, flags=re.IGNORECASE)[0]
        destination = f"{ENTRYPOINT_FOLDER}/{name}"
        command_content += f"""
            mkdir -p {destination}
            aws s3 cp {content} {SIDECAR_CONTAINER_FOLDER}
            unzip {SIDECAR_CONTAINER_FOLDER}/{zip_file} -d {destination}
        """
    command_sidecar_failure = ""
    if token == "":
        command_activity_stop = ""
    else:
        # The `--cause` parameter for `send-task-failure` has a limit of 32768 characters
        command_activity_stop = f"""
            result="$(cat {MAIN_CONTAINER_FOLDER}/complete)"
            if [ "$result" -eq 0 ]; then
                aws stepfunctions send-task-success --task-token "{token}" --task-output '{{"output": "$result"}}' --region "{region}"
            else
                aws stepfunctions send-task-failure --task-token "{token}" --error "NonZeroExitCode" --cause "$(cat {MAIN_CONTAINER_FOLDER}/error_header.log; cat {MAIN_CONTAINER_FOLDER}/main.log | tail -c 32000 | tail -15)"
            fi
        """
        command_sidecar_failure = f"""
            if [ ! "$(cat {SIDECAR_CONTAINER_FOLDER}/exitcode)" -eq 0 ]; then
                retries=0
                while [ "$retries" -lt 5 ]; do
                    aws stepfunctions send-task-failure --task-token "{token}" --error "NonZeroExitCode" --cause "$(cat {SIDECAR_CONTAINER_FOLDER}/error_header.log; cat {SIDECAR_CONTAINER_FOLDER}/sidecar.log | tail -c 32000 | tail -15)" && break
                    retries="$((retries+1))"
                    echo "Failed to report sidecar failure"
                done
            fi
        """

    command_init_complete = f"touch {SIDECAR_CONTAINER_FOLDER}/init-complete"
    command_wait = f"""
        await_main_complete
        echo "main exited with status code $(cat {MAIN_CONTAINER_FOLDER}/complete)"
    """

    command_str = f"""
        mkdir -p {SIDECAR_CONTAINER_FOLDER}
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
        echo $? > {SIDECAR_CONTAINER_FOLDER}/exitcode
        }} 2>&1 | tee {SIDECAR_CONTAINER_FOLDER}/sidecar.log
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
