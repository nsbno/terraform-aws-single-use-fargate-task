output "test_data_for_lambda" {
  value = <<-EOF
{
    "ecs_cluster": "${local.name_prefix}-single-tasks",
    "cmd_to_run": "echo \"Hello World\"",
    "image": "vydev/terraform:0.12.20",
    "subnets": [${local.subnets}],
    "task_execution_role_arn": "${local.name_prefix}-ECSTaskExecutionRole",
    "task_role_arn": "${aws_iam_role.ecs_task_role.arn}"
}
EOF
}