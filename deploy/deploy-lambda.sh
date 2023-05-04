#!/bin/bash
#
# Script to create a zipped deployment package for a Lambda function.
#
# Command line arguments:
# [1] app_name: Name of application to create a zipped deployment package for
# 
# Example usage: ./delpoy-lambda.sh "my-app-name"

APP_NAME=$1
ROOT_PATH="$PWD"

# Install dependencies
pip install --target $ROOT_PATH/package requests

# Zip dependencies
mkdir -p $ROOT_PATH/package
cd $ROOT_PATH/package
zip -r $ROOT_PATH/$APP_NAME.zip .

# Zip script
cd $ROOT_PATH
echo $(ls $ROOT_PATH)
zip -u $APP_NAME.zip $APP_NAME.py
echo "Created: $ZIP_PATH."
