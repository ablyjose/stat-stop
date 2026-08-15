import os
import math
import boto3
import json
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import dotenv_values


def safe_float(value, default=0.0):
    """Convert a value to float, replacing NaN/Infinity with a default."""
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default

config = dotenv_values()

R2_ENDPOINT_URL = config.get("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = config.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = config.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = config.get("R2_BUCKET_NAME")

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

def _sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization, replacing NaN/Inf with None."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(item) for item in obj]
    return obj


def set_json_cache(key: str, data: dict):
    client = get_r2_client()
    if not client:
        return False
    try:
        sanitized = _sanitize_for_json(data)
        client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=key,
            Body=json.dumps(sanitized),
            ContentType='application/json'
        )
        return True
    except Exception as e:
        print(f"Error writing cache for key {key}: {e}")
        return False

def check_cache_exists(key: str):
    client = get_r2_client()
    if not client:
        return False
    try:
        client.head_object(Bucket=R2_BUCKET_NAME, Key=key)
        return True
    except ClientError as e:
        return False
    except Exception as e:
        return False

