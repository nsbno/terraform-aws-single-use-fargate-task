terraform {
  required_version = ">= 0.12"
}

provider "aws" {
  version = ">= 2.44"
  region  = "eu-west-1"
}

locals {
  name_prefix = "test"
  tags = {
    terraform   = "true"
    environment = "test"
  }
}

module "single_use_fargate_task" {
  source      = "../../"
  name_prefix = local.name_prefix
  tags        = local.tags
}

data "aws_availability_zones" "main" {}
locals {
  vpc_cidr_block = "192.168.50.0/24"
  public_cidr_blocks = [for k, v in data.aws_availability_zones.main.names :
  cidrsubnet(local.vpc_cidr_block, 4, k)]
}
module "vpc" {
  source               = "github.com/nsbno/terraform-aws-vpc?ref=ec7f57f"
  name_prefix          = local.name_prefix
  cidr_block           = local.vpc_cidr_block
  availability_zones   = data.aws_availability_zones.main.names
  public_subnet_cidrs  = local.public_cidr_blocks
  create_nat_gateways  = false
  enable_dns_hostnames = true
  tags                 = local.tags
}

locals {
  subnets = join(", ", formatlist("\"%s\"", module.vpc.public_subnet_ids))
}

resource "aws_iam_role" "ecs_task_role" {
  name               = "${local.name_prefix}-single-use-tasks"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
resource "aws_iam_role_policy" "pass_role_to_single_task_lambda" {
  policy = data.aws_iam_policy_document.pass_role_for_lambda.json
  role   = module.single_use_fargate_task.lambda_exec_role_id
}

