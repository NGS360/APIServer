# APIServer

## Launching Stack

```bash
docker compose up
```

## Deployment to AWS Elastic Beanstalk

This project includes a GitHub Actions workflow for automatically deploying to AWS Elastic Beanstalk when changes are pushed to the main branch.

### Prerequisites

Before you can use the deployment workflow, you need to set up the following GitHub secrets:

1. `AWS_ACCESS_KEY_ID`: Your AWS access key with permissions to deploy to Elastic Beanstalk
2. `AWS_SECRET_ACCESS_KEY`: Your AWS secret access key
3. `AWS_REGION`: The AWS region where your Elastic Beanstalk environment is located (e.g., `us-east-1`)
4. `EB_APPLICATION_NAME`: The name of your Elastic Beanstalk application (e.g., `NGS360-APIServer`)
5. `EB_ENVIRONMENT_NAME`: The name of your Elastic Beanstalk environment (e.g., `dev`)

### How to Set Up GitHub Secrets

1. Go to your GitHub repository
2. Click on "Settings" > "Secrets and variables" > "Actions"
3. Click on "New repository secret"
4. Add each of the secrets listed above

### Deployment Workflow

The deployment workflow performs the following steps:

1. Runs tests to ensure the code is working correctly
2. Creates a deployment package (ZIP file)
3. Deploys the package to AWS Elastic Beanstalk

The workflow runs automatically when changes are pushed to the main branch. You can also trigger the workflow manually from the "Actions" tab in GitHub.

### Manual Deployment

To manually trigger a deployment:

1. Go to the "Actions" tab in your GitHub repository
2. Select the "Deploy to Elastic Beanstalk" workflow
3. Click on "Run workflow"
4. Select the branch you want to deploy and click "Run workflow"
