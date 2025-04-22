# APIServer

This is the REST API Server for NGS360, representing the Model and Controller components

## Launching Stack

There are really three ways to run this app:

1. docker compose up

This will launch the database myphp in two docker containers, then run the app in a third container using boot.sh with environment settings from compose.yaml

2. boot.sh

This will launch to app from the shell using the environment settings in .env.  This assumes the db is already running.  This mechanism assist for development and debugging.

3.  CloudFormation

Using Cloudformatin, you can deploy this app to ElasticBeanStalk.  There are two CloudFormation templates:

1. cloudformation-db.yaml
2. cloudformation.yaml

We maintain two stacks such that if the Beanstalk stack is accidentally deleted, the database will live on.

Once ElasticBeanStalk CLI is set up and application/environment are established, use

eb deploy


