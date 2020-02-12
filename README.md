## Single Use Fargate Task

This module provides a way of simply running ad-hoc containers in Fargate.

The module creates a Lambda that can be called to run a command of your choosing in a container of your choice with a
volume of content from s3 mounted.

The task can optionally be tracked by an AWS step functions Activity


### Expected Attributes
The lambda expects a json input with the following attributes

#### activity_arn (Optional)
The arn of a step function activity that this task will register itself to and report its outcome to.

#### cmd_to_run
A command to be run in the container - this will be run after any content has been unzipped

#### content (Optional)
The s3 uri of a zip file to be unzipped into a folder mounted at `/tmp/workspace`.

#### ecs_cluster
The name of the ECS cluster on which to run the fargate task

#### image
The docker uri of the container image to launch

#### subnets
A list of subnets into which this fargate container can be launched

#### task_execution_role_arn
The arn of the role given to Fargate to run tasks - this is typically a role with the managed 
`AmazonECSTaskExecutionRolePolicy` policy attached

#### task_role_arn
The arn of the role the task will assume when running

###### Example
```json
{
  "activity_arn": "<activity_arn>",
  "cmd_to_run": "echo \"Hello World\"",
  "content": "<s3_uri>",
  "ecs_cluster": "test-single-tasks",
  "image": "vydev/terraform:0.12.20",
  "subnets": [
    "<subnet-1>",
    "<subnet-2>",
    "<subnet-2>"
  ],
  "task_execution_role_arn": "test-ECSTaskExecutionRole",
  "task_role_arn": "<task_role_arn>"
}
```