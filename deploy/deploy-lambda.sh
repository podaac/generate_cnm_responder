#!/bin/bash
#
# Script to deploy a zipped package to an AWS Lambda Function
#
# Command line arguments:
# [1] function_name: Name of AWS Lambda function name
# [2] app_name: Name of application for zipped deployment
# 
# Example usage: ./delpoy-lambda.sh "my-lambda-function" "my-app-name"

FUNCTION_NAME=$1
APP_NAME=$2

ROOT_PATH="$PWD"
ZIP_PATH=$ROOT_PATH/$APP_NAME.zip

response=$(aws lambda update-function-code --function-name $FUNCTION_NAME --zip-file $ZIP_PATH)

aws lambda wait function-updated-v2 --function-name $FUNCTION_NAME

echo "Zipped package has been deployed to Lambda."
