## examples/default

This example creates an instance of the single-use-fargate-task lambda and
outputs a json document that can be used as sample test data for input to 
the lambda when testing it. 

#### Quick Start
1. `terraform init`
2. `terraform apply`
3. Copy the json part of the output `test_data_for_lambda` and paste it into the "Configure test event"
dialog
4. Test the lambda with the test data
5. View results in Cloudwatch logs

Logs for the lambda:
/aws/lambda/test-run-single-task

Logs for the container
/aws/ecs/single-use-tasks

*Note* there are 2 streams for the task 1 for the container you specify and one for the orchestration sidecar