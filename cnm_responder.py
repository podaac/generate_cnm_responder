"""AWS Lambda that handles CNM responses published to an SNS Topic.

Deletes successfully ingested L2P granules from S3 bucket and EFS.
Logs the errors.
"""

# Standard imports
import datetime
import json
import logging
import pathlib
import sys

# Third-party imports
import boto3
import botocore
import requests

# Constants
EFS = {
    "MODIS_A": "MODIS_L2P_CORE_NETCDF",
    "MODIS_T": "MODIS_L2P_CORE_NETCDF",
    "VIIRS": "VIIRS_L2P_CORE_NETCDF"
}
S3 = {
    "MODIS_A": "aqua",
    "MODIS_T": "terra",
    "VIIRS": "viirs"
}
DATASET_DICT = {
    "MODIS_A": "MODIS_A-JPL-L2P-v2019.0",
    "MODIS_T": "MODIS_T-JPL-L2P-v2019.0",
    "VIIRS": "VIIRS_NPP-JPL-L2P-v2016.2"
}
OUTPUT = pathlib.Path("/mnt/data")
TOPIC_STRING = "batch-job-failure"

def cnm_handler(event, context):
    """Handles CNM responses delivered from SNS Topic."""
    
    logger = get_logger()
    logger.info(f"EVENT - {event}")
    
    # Parse message
    response = json.loads(event["Records"][0]["Sns"]["Message"])
    collection = response["collection"]
    
    # Determine success or failure
    event_response = response["response"]["status"]
    if event_response == "FAILURE":
        message = f"{response['response']['errorCode']}: {response['response']['errorMessage']}"
        handle_failure(message, response["identifier"], collection, logger)
    else:
        # Search
        logger.info(f"Granule possibly ingested for: {collection}. Confirming now.")
        if response["trace"].endswith("-sit") or response["trace"].endswith("-uat"):
            cmr_url = "https://cmr.uat.earthdata.nasa.gov/search/granules.umm_json"
        else:
            cmr_url = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
        granule_name = response["identifier"]
        try:
            token = get_edl_token(response["trace"], logger)
        except botocore.exceptions.ClientError as error:
            handle_failure(error, granule_name, collection, logger)
        logger.info(f"Searching for {granule_name} from {collection}.")
        checksum_dict = run_query(cmr_url, collection, granule_name, token, logger)
        
        # Remove file from S3 if present
        if checksum_dict:
            logger.info(f"Found {granule_name} from {collection}.")
            try:
                d_name = granule_name.split('-')[4]
                if "VIIRS" in d_name: d_name = d_name.replace("_NPP", "")
                dataset = S3[d_name]
                checksum_errors = remove_staged_file(checksum_dict, response["trace"], dataset, response["product"]["files"], logger)
                # Report on any files where checksums did not match
                if len(checksum_errors) > 0: report_checksum_errors(checksum_errors, logger)
            except botocore.exceptions.ClientError as error:
                handle_failure(error, granule_name, collection, logger)
        else:
            message = f"Searched failed for {granule_name} from {collection}." 
            handle_failure(message, granule_name, collection, logger)
            
        # Remove file from EFS output directory
        logger.info(f"Removing {granule_name} from processor L2P output.")
        remove_from_efs(f"{granule_name}.nc", logger)      
    
def get_logger():
    """Return a formatted logger object."""
    
    # Remove AWS Lambda logger
    logger = logging.getLogger()
    for handler in logger.handlers:
        logger.removeHandler(handler)
    
    # Create a Logger object and set log level
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Create a handler to console and set level
    console_handler = logging.StreamHandler()

    # Create a formatter and add it to the handler
    console_format = logging.Formatter("%(asctime)s - %(module)s - %(levelname)s : %(message)s")
    console_handler.setFormatter(console_format)

    # Add handlers to logger
    logger.addHandler(console_handler)

    # Return logger
    return logger

def handle_failure(message, granule, collection, logger):
    """Log CNM response failure message and send a notification."""
    
    logger.error(f"Cumulus ingestion failed for {granule} in {collection}")
    logger.error(message)
    error_message = f"Cumulus ingestion failed for {granule} in {collection}.\n" \
        + message
    publish_event(error_message, logger)
    logger.error("Exiting program.")
    sys.exit(1)
    
def publish_event(error_msg, logger):
    """Publish event to SNS Topic."""
    
    sns = boto3.client("sns")
    
    # Get topic ARN
    try:
        topics = sns.list_topics()
    except botocore.exceptions.ClientError as e:
        logger.error("Failed to list SNS Topics.")
        logger.error(f"Error - {e}")
        sys.exit(1)
    for topic in topics["Topics"]:
        if TOPIC_STRING in topic["TopicArn"]:
            topic_arn = topic["TopicArn"]
            
    # Publish to topic
    subject = f"Generate Failure: CNM Responder"
    try:
        response = sns.publish(
            TopicArn = topic_arn,
            Message = error_msg,
            Subject = subject
        )
    except botocore.exceptions.ClientError as e:
        logger.error(f"Failed to publish to SNS Topic: {topic_arn}.")
        logger.error(f"Error - {e}")
        sys.exit(1)
    
    logger.info(f"Message published to SNS Topic: {topic_arn}.")
    
def get_edl_token(prefix, logger):
    """Retrieve EDL bearer token from SSM parameter store."""
    
    try:
        ssm_client = boto3.client('ssm', region_name="us-west-2")
        token = ssm_client.get_parameter(Name=f"{prefix}-edl-token", WithDecryption=True)["Parameter"]["Value"]
        logger.info("Retrieved EDL token.")
        return token
    except botocore.exceptions.ClientError as error:
        logger.error("Could not retrieve EDL credentials from SSM Parameter Store.")
        raise error

def run_query(cmr_url, collection, granule_name, token, logger):
    """Run query on granule to see if it exists in CMR.
    
    Returns dict of file and md5 checksums or empty dict if no granule is found.
    """

    # Search for granule
    headers = { "Authorization": f"Bearer {token}" }
    params = {
        "short_name": collection,
        "readable_granule_name": granule_name
    }
    res = requests.post(url=cmr_url, headers=headers, params=params)        
    coll = res.json()

    # Parse response to locate granule checksums
    if "errors" in coll.keys():
        logger.error(f"Error response - {coll['errors']}")
        return {}
    elif "hits" in coll.keys() and coll["hits"] > 0:
        files = coll["items"][0]["umm"]["DataGranule"]["ArchiveAndDistributionInformation"]
        checksum_dict = {}
        for file in files:
            if file["Name"].endswith(".nc"):
                checksum_dict["netcdf"] = file["Checksum"]["Value"]
            if file["Name"].endswith(".md5"):
                checksum_dict["md5"] = file["Checksum"]["Value"]
        return checksum_dict
    else:
        logger.error(f"Could not locate granule: {granule_name}")
        return {}
    
def remove_staged_file(checksum_dict, prefix, dataset, file_list, logger):
    """Remove files that were staged in L2P granules S3 bucket."""
    
    checksum_errors = []
    for file in file_list:
        if file["name"].endswith(".nc"):
            file_type = "netcdf"
        elif file["name"].endswith(".md5"):
            file_type = "md5"
        else:
            continue 
        # Remove file from S3 if checksums match
        if file["checksum"] == checksum_dict[file_type]:
            try:
                s3 = boto3.client("s3")
                response = s3.delete_object(
                    Bucket=f"{prefix}-l2p-granules",
                    Key=f"{dataset}/{file['name']}"
                )
                logger.info(f"{dataset}/{file['name']} deleted from L2P granules staging bucket.")
            except botocore.exceptions.ClientError as error:
                logger.error(f"Error encountered deleting file: {file['name']}")
                raise error
        else:
            checksum_errors.append(file["name"])
            
    return checksum_errors
        
def report_checksum_errors(checksum_errors, logger):
    """Report on cases where S3 checksum did not match CMR checksum."""
    
    logger.error("The following checksums created during Generate processing did not match checksums found in CMR...")
    for file in checksum_errors:
        logger.error(file)
    sys.exit(1)
    
def remove_from_efs(granule_name, logger):
    """Remove L2P granule from processor output directory."""
    
    dataset = granule_name.split('-')[4]
    if "VIIRS" in dataset: dataset = dataset.replace("_NPP", "")
    ts = datetime.datetime.strptime(granule_name.split('-')[0], "%Y%m%d%H%M%S")

    granule_file = OUTPUT.joinpath(EFS[dataset], dataset, str(ts.year), str(ts.timetuple().tm_yday), granule_name)   
    delete_file(granule_file, logger)
        
    checksum = OUTPUT.joinpath(EFS[dataset], dataset, str(ts.year), str(ts.timetuple().tm_yday), f"{granule_name}.md5")
    delete_file(checksum, logger)
    
    granule_file_refined = OUTPUT.joinpath(EFS[dataset], f"{dataset}_REFINED", str(ts.year), str(ts.timetuple().tm_yday), granule_name)
    delete_file(granule_file_refined, logger)
    
    checksum_refined = OUTPUT.joinpath(EFS[dataset], f"{dataset}_REFINED", str(ts.year), str(ts.timetuple().tm_yday), f"{granule_name}.md5")
    delete_file(checksum_refined, logger)

def delete_file(granule, logger):
    """Determine if granule file exists and delete if it does.
    
    Returns granule name if does not exist else None.
    """
    
    try:
        granule.unlink()
        logger.info(f"Removed {str(granule)} from EFS.")
    except FileNotFoundError:
        logger.info(f"{str(granule)} does not exist on the EFS.")
