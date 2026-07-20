import os
import boto3
import json
from botocore.config import Config
from botocore.exceptions import ClientError

R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")

def get_r2_client():
    if not all([R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        return None
    try:
        return boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4")
        )
    except Exception as e:
        print(f"Error initializing R2 client: {e}")
        return None

def get_json_cache(key: str):
    client = get_r2_client()
    if not client:
        return None
    try:
        response = client.get_object(Bucket=R2_BUCKET_NAME, Key=key)
        return json.loads(response['Body'].read().decode('utf-8'))
    except ClientError as e:
        if e.response['Error']['Code'] != 'NoSuchKey':
            print(f"Error reading cache for key {key}: {e}")
        return None
    except Exception as e:
        print(f"Error parsing cache for key {key}: {e}")
        return None

def set_json_cache(key: str, data: dict):
    client = get_r2_client()
    if not client:
        return False
    try:
        client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=key,
            Body=json.dumps(data),
            ContentType='application/json'
        )
        return True
    except Exception as e:
        print(f"Error writing cache for key {key}: {e}")
        return False

