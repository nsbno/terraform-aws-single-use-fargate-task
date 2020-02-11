output "test_data_for_lambda" {
  value = <<-EOF
{
    "content": "",
    "activity_arn": "",
    "task_execution_role_arn": "${local.name_prefix}-ECSTaskExecutionRole",
    "ecs_cluster": "${local.name_prefix}-single-tasks",
    "subnets": [${local.subnets}],
    "image": "vydev/terraform:0.12.20",
    "cmd_to_run": "echo \"Hello World\"",
    "task_role_arn": "${aws_iam_role.ecs_task_role.arn}"
}
EOF
}