# cnm_responder

The cnm_responder program is an AWS Lambda function that processes CNM responses.

It deletes L2P granules from the appropriate S3 bucket for successes and it logs ingestion failure to a CloudWatch logs.

Top-level Generate repo: https://github.com/podaac/generate

## aws infrastructure

The cnm_responder program includes the following AWS services:
- Lambda function to execute code deployed via zip file.
- Permissions that allow an SNS Topic to invoke the Lambda function.
- IAM role and policy for Lambda function execution.

## terraform 

Deploys AWS infrastructure and stores state in an S3 backend. Terraform deployment is the same for both `cnm_responder` and `token_creator`.

To deploy:
1. Initialize terraform: 
    ```
    terraform init -backend-config="bucket=bucket-state" \
        -backend-config="key=component.tfstate" \
        -backend-config="region=aws-region" \
        -backend-config="profile=named-profile"
    ```
2. Plan terraform modifications: 
    ```
    ~/terraform plan -var="environment=venue" \
        -var="prefix=venue-prefix" \
        -var="profile=named-profile" \
        -out="tfplan"
    ```
3. Apply terraform modifications: `terraform apply tfplan`

`{prefix}` is the account or environment name.