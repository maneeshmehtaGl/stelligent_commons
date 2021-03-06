#!/usr/bin/env python

import boto
import boto.cloudtrail
import json
import logging
import re


def get_aws_account_id():
    """ Return AWS Account Id """

    return boto.connect_iam().get_user().arn.split(':')[4]


def ensure_s3_bucket(bucket_name):
    """ Verify that the specified archive bucket exists """

    s3_conn = boto.connect_s3()
    archive_bucket = None
    try:
        archive_bucket = s3_conn.get_bucket(bucket_name)
    except Exception as e:
        if e.status != 404:
            raise e

    if not archive_bucket:
        logging.info('Bucket does not exist. Creating ' + bucket_name)
        archive_bucket = s3_conn.create_bucket(bucket_name=bucket_name)

    return archive_bucket


def get_aws_cloudtrail_aclcheck_s3_policy_statement(s3_bucket_name):
    """ Return dictionary (that should be converted to json) of AWSCloudTrailAclCheck policy """

    # Grabbed from:
    # http://docs.aws.amazon.com/awscloudtrail/latest/userguide/create-s3-bucket-policy-for-cloudtrail.html
    return {
        "Sid": "AWSCloudTrailAclCheck20131101",
        "Effect": "Allow",
        "Principal": {
            "AWS": [
                "arn:aws:iam::903692715234:root",
                "arn:aws:iam::859597730677:root",
                "arn:aws:iam::814480443879:root",
                "arn:aws:iam::216624486486:root",
                "arn:aws:iam::086441151436:root",
                "arn:aws:iam::388731089494:root",
                "arn:aws:iam::284668455005:root",
                "arn:aws:iam::113285607260:root",
                "arn:aws:iam::035351147821:root"
            ]
        },
        "Action": "s3:GetBucketAcl",
        "Resource": "arn:aws:s3:::%s" % s3_bucket_name
    }


def get_aws_cloudtrail_write_s3_policy_statement(aws_account_id, s3_bucket_name, s3_prefix=''):
    """ Return dictionary (that should be converted to json) of AWSCloudTrailWrite policy """

    # Grabbed from:
    # http://docs.aws.amazon.com/awscloudtrail/latest/userguide/create-s3-bucket-policy-for-cloudtrail.html
    return {
        "Sid": "AWSCloudTrailWrite20131101",
        "Effect": "Allow",
        "Principal": {
            "AWS": [
                "arn:aws:iam::903692715234:root",
                "arn:aws:iam::859597730677:root",
                "arn:aws:iam::814480443879:root",
                "arn:aws:iam::216624486486:root",
                "arn:aws:iam::086441151436:root",
                "arn:aws:iam::388731089494:root",
                "arn:aws:iam::284668455005:root",
                "arn:aws:iam::113285607260:root",
                "arn:aws:iam::035351147821:root"
            ]
        },
        "Action": "s3:PutObject",
        "Resource": "arn:aws:s3:::%s%s/AWSLogs/%s/*" % (s3_bucket_name, s3_prefix, aws_account_id),
        "Condition": {
            "StringEquals": {
                "s3:x-amz-acl": "bucket-owner-full-control"
            }
        }
    }


def ensure_bucket_policy(s3_bucket, s3_prefix=''):
    """ Verify that the specified S3 bucket has policy allowing CloudTrail to write to it """

    existing_bucket_policy_str = None
    try:
        existing_bucket_policy_str = s3_bucket.get_policy()
    except Exception as e:
        if e.status != 404:
            raise e

    # base headers of new policy
    new_policy = {'Version': '2012-10-17', 'Statement': []}

    # if we have an existing bucket policy, strip out cloudtrail statements
    if existing_bucket_policy_str:
        logging.info('Existing bucket policy found for bucket ' + s3_bucket.name)
        existing_bucket_policy = json.loads(existing_bucket_policy_str)
        for policy_statement in existing_bucket_policy['Statement']:
            if not re.match('^AWSCloudTrailAclCheck|AWSCloudTrailWrite', policy_statement['Sid']):
                new_policy['Statement'].append(policy_statement)
                logging.info('Maintaining policy Sid: ' + policy_statement['Sid'])
            else:
                logging.info('Stripping out policy Sid: ' + policy_statement['Sid'])

    # append cloudtrail statements
    new_policy['Statement'].append(get_aws_cloudtrail_aclcheck_s3_policy_statement(s3_bucket.name))
    logging.info('Adding new CloudTrail ACL Check S3 Bucket Policy')
    new_policy['Statement'].append(get_aws_cloudtrail_write_s3_policy_statement(get_aws_account_id(), s3_bucket.name, s3_prefix))
    logging.info('Adding new CloudTrail Write S3 Bucket Policy')

    s3_bucket.set_policy(json.dumps(new_policy, indent=2))


def ensure_cloudtrail_for_region(region_name, s3_bucket, s3_prefix=''):
    """ Ensure CloudTrail is sending to logs to s3_bucket for the specified region """

    cloudtrail_conn = boto.cloudtrail.connect_to_region(region_name)
    trail_list = cloudtrail_conn.describe_trails()['trailList']

    # if CloudTrail is not enabled, fire it up!
    if not trail_list:
        trail_name = 'Default'
        cloudtrail_conn.create_trail(trail_name,
                                     s3_bucket_name=s3_bucket.name,
                                     s3_key_prefix=s3_prefix,
                                     include_global_service_events=True)

    else:
        trail_name = trail_list[0]['Name']
        cloudtrail_conn.update_trail(trail_name,
                                     s3_bucket_name=s3_bucket.name,
                                     s3_key_prefix=s3_prefix,
                                     include_global_service_events=True)

    cloudtrail_conn.start_logging(trail_name)


def get_cloudtrail_regions():
    """ Return list of names of regions in CloudTrail is available """

    cloudtrail_regioninfo_list = boto.regioninfo.get_regions('cloudtrail')
    return [r.name for r in cloudtrail_regioninfo_list]


def ensure_cloudtrail(s3_bucket, s3_prefix=''):
    """ Ensure CloudTrail is sending to logs to s3_bucket for the specified region """

    for region_name in get_cloudtrail_regions():
        logging.info('Ensuring CloudTrail is logging to ' + s3_bucket.name + s3_prefix + ' in region ' + region_name)
        ensure_cloudtrail_for_region(region_name, s3_bucket, s3_prefix)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Enable CloudTrail logging to S3 in all regions',
                                     epilog='--bucket must be specified')
    parser.add_argument('-b', '--bucket', dest='bucket_name',
                        help='S3 Bucket to which CloudTrail logs are sent. Bucket must already exist. (aws s3 mb s3://your-bucket-name)')
    parser.add_argument('-p', '--prefix', dest='s3_prefix', default='',
                        help='Prefix to log path in S3 bucket')
    args = parser.parse_args()

    if not (args.bucket_name):
        parser.print_help()
        exit(1)

    logging.basicConfig(format='%(asctime)s: %(message)s', datefmt='%m/%d/%Y %H:%M:%S %Z', level=logging.INFO)

    s3_bucket = ensure_s3_bucket(args.bucket_name)
    ensure_bucket_policy(s3_bucket, args.s3_prefix)
    ensure_cloudtrail(s3_bucket, args.s3_prefix)
