terraform {
  required_version = ">= 0.12"
}

provider "aws" {
  version = ">= 2.44"
  region = "eu-west-1"
}

locals{
  name_prefix = "test"
  tags = {
    terraform = "true"
    environment = "test"
  }
}

module "single_use_fargate_task" {
  source = "../../"
  name_prefix = local.name_prefix
  tags = local.tags
}