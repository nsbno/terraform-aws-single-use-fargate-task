output "function_name" {
  description = "The name of the Lambda function."
  value       = aws_lambda_function.run_single_fargate_task.id
}

output "lambda_exec_role_id" {
  description = "The name of the execution role given to the lambda."
  value       = aws_iam_role.lambda_exec.id
}

output "task_execution_role_arn" {
  description = "The arn of the ESCTaskExecutionRole created"
  value       = aws_iam_role.task_execution_role.arn
}