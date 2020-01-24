## Single Use Fargate Task

This module provides a way of simply running ad-hoc containers in Fargate.

The module creates a Lambda that can be called to run a command of your choosing in a container of your choice with a
volume of content from s3 mounted.

```$xslt
{
  "image": "colincoleman/circleci-ecr:latest",
  "content": "s3://111222333444-pipeline-artifact/step-pipeline/12345.zip",
  "file_to_run": "entrypoint.sh"
  "ecs_cluster": "test-single-tasks"
}
```