# APIServer

This is the REST API Server for NGS360, representing the Model and Controller components

## Launching Stack

There are really two ways to run this app:

1. docker compose up

This will launch the database myphp in two docker containers, then run the app in a third container using boot.sh with environment settings from compose.yaml

2. boot.sh

This will launch to app from the shell using the environment settings in .env.  This assumes the db is already running.  This mechanism assist for development and debugging.

