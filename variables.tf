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
  description = "Optional ARN of a KMS key to use for encrypting the CloudWatch logs."
  type        = string
  default     = null
}

variable "tags" {
  description = "A map of tags (key-value pairs) passed to resources."
  type        = map(string)
  default     = {}
}

