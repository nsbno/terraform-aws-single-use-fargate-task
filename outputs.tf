output "function_name" {
  value = aws_lambda_function.run_single_fargate_task.id
}

output "lambda_exec_role_id" {
  value = aws_iam_role.lambda_exec.id
}