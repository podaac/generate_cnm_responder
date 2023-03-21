"""AWS Lambda that handles CNM responses published to an SNS Topic.

Deletes successfully ingested L2P granules.
Logs the errors.
"""

# Standard imports
import logging
import sys

# Third-party imports
import boto3
import botocore
import requests

# Constants
CMR_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"

def cnm_handler(event, context):
    """Handles CNM responses delivered from SNS Topic."""
    
    logger = get_logger()
    
    # Deterime success or failure
    event_response = event["response"]["status"]
    if event_response == "FAILURE":
        message = f"{event['response']['errorCode']}: {event['response']['errorMessage']}"
        log_failure(message, event["identifier"], event["collection"], logger)
    else:
        # Search
        collection_id = event["response"]["ingestionMetadata"]["catalogId"]
        granule_name = event["identifier"]
        logger.info(f"Searching for {granule_name} from {collection_id}.")
        checksum_dict = run_query(collection_id, granule_name)
        
        # Remove file from S3 if present
        if checksum_dict:
            logger.info(f"Found {granule_name} from {collection_id}.")
            try:
                checksum_errors = remove_staged_file(checksum_dict, event["trace"], event["product"]["files"], logger)
                # Report on any files where checksums did not match
                if len(checksum_errors) > 0: report_checksum_errors(checksum_errors, logger)
            except botocore.exceptions.ClientError as error:
                log_failure(error, granule_name, event["collection"], logger)
        else:
            message = f"Searched failed for {granule_name} from {collection_id}." 
            log_failure(message, granule_name, event["collection"], logger)
    
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

def log_failure(message, granule, collection, logger):
    """Log CNM response failure message."""
    
    logger.error(f"Cumulus ingestion failed for {granule} in {collection}")
    logger.error(message)
    logger.error("Exiting program.")
    sys.exit(1)

def run_query(collection_id, granule_name):
    """Run query on granule to see if it exists in CMR.
    
    Returns dict of file and md5 checksums or empty dict if no granule is found.
    """

    # Search for granule
    params = {
        "concept_id": collection_id,
        "readable_granule_name": granule_name
    }
    res = requests.get(url=CMR_URL, params=params)        
    coll = res.json()

    # Parse response to locate granule checksums
    if coll["hits"] > 0:
        files = coll["items"][0]["umm"]["DataGranule"]["ArchiveAndDistributionInformation"]
        checksum_dict = {}
        for file in files:
            if file["Name"].endswith(".nc"):
                checksum_dict["netcdf"] = file["Checksum"]["Value"]
            if file["Name"].endswith(".md5"):
                checksum_dict["md5"] = file["Checksum"]["Value"]
        return checksum_dict
    else:
        return {}
    
def remove_staged_file(checksum_dict, prefix, file_list, logger):
    """Remove files that were staged in L2P granules S3 bucket."""
    
    checksum_errors = []
    for file in file_list:
        file_type = "netcdf" if file["name"].endswith(".nc") else "md5"
        # Remove file from S3 if checksums match
        if file["checksum"] == checksum_dict[file_type]:
            try:
                s3 = boto3.client("s3")
                response = s3.delete_object(
                    Bucket=f"{prefix}-l2p-granules",
                    Key=file['name']
                )
                logger.info(f"{file['name']} deleted from L2P granules staging bucket.")
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