# ------------------------------------------------------------------------------
# Resources
# ------------------------------------------------------------------------------
data "aws_caller_identity" "current-account" {}
data "aws_region" "current" {}

locals {
  current_account_id = data.aws_caller_identity.current-account.account_id
  current_region     = data.aws_region.current.name
}

data "archive_file" "lambda_src" {
  type        = "zip"
  source_file = "${path.module}/src/run-single-fargate-task.py"
  output_path = "${path.module}/src/run-single-fargate-task.zip"
}

resource "aws_lambda_function" "run_single_fargate_task" {
  function_name    = "${var.name_prefix}-run-single-task"
  handler          = "run-single-fargate-task.lambda_handler"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "python3.7"
  filename         = data.archive_file.lambda_src.output_path
  source_code_hash = filebase64sha256(data.archive_file.lambda_src.output_path)
  timeout          = var.lambda_timeout
  environment {
    variables = {
      SIDECAR_LOG_GROUP_NAME = aws_cloudwatch_log_group.sidecar.name
      MAIN_LOG_GROUP_NAME    = aws_cloudwatch_log_group.main.name
    }
  }
  tags = var.tags
}

resource "aws_iam_role" "lambda_exec" {
  name               = "${var.name_prefix}-run-single-task"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "logs_to_lambda" {
  policy = data.aws_iam_policy_document.logs_for_lambda.json
  role   = aws_iam_role.lambda_exec.id
}

resource "aws_iam_role_policy" "ecs_to_lambda" {
  policy = data.aws_iam_policy_document.ecs_for_lambda.json
  role   = aws_iam_role.lambda_exec.id
}

resource "aws_ecs_cluster" "ecs_cluster" {
  name = "${var.name_prefix}-single-tasks"
  tags = var.tags
}

resource "aws_iam_role" "task_execution_role" {
  name               = "${var.name_prefix}-ECSTaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "ECSTaskExecution" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
  role       = aws_iam_role.task_execution_role.id
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.run_single_fargate_task.function_name}"
  retention_in_days = var.lambda_log_retention_in_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "sidecar" {
  name              = "/aws/ecs/${var.name_prefix}-single-use-tasks/sidecar"
  kms_key_id        = var.kms_key_arn
  retention_in_days = var.container_log_retention_in_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "main" {
  name              = "/aws/ecs/${var.name_prefix}-single-use-tasks/main"
  kms_key_id        = var.kms_key_arn
  retention_in_days = var.container_log_retention_in_days
  tags              = var.tags
}
