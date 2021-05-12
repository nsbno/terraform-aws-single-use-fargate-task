# ------------------------------------------------------------------------------
# Variables
# ------------------------------------------------------------------------------
variable "name_prefix" {
  description = "A prefix used for naming resources."
  type        = string
}

variable "lambda_timeout" {
  description = "The maximum number of seconds the Lambda is allowed to run."
  default     = 10
}

variable "kms_key_arn" {
  description = "Optional ARN of a KMS key to use for encrypting the CloudWatch logs associated with a Fargate task."
  type        = string
  default     = null
}

variable "container_log_retention_in_days" {
  description = "The number of days to retain CloudWatch logs associated with a Fargate task."
  default     = 30
}

variable "lambda_log_retention_in_days" {
  description = "The number of days to retain CloudWatch logs from the Lambda."
  default     = 14
}

variable "tags" {
  description = "A map of tags (key-value pairs) passed to resources."
  type        = map(string)
  default     = {}
}

