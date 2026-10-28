import os
import math
import time
import boto3
import json
from pathlib import Path
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

# Added for Vercel environment compatibility
_local_config = dotenv_values(Path(__file__).with_name(".env"))


def _get_config_value(name: str):
    return os.environ.get(name) or _local_config.get(name)


R2_ENDPOINT_URL = _get_config_value("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = _get_config_value("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = _get_config_value("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = _get_config_value("R2_BUCKET_NAME")

TELEMETRY_CACHE_REVISION = "v3"


def telemetry_cache_key(year: int, gp: str, session: str, driver: str, lap: str) -> str:
    """Build the current-version cache key for one driver's lap telemetry."""
    return f"telemetry/{TELEMETRY_CACHE_REVISION}/{year}/{gp}/{session}/{driver}_{lap}.json"


def telemetry_completion_key(year: int, gp: str, session: str) -> str:
    """Only trust markers written after every driver upload succeeded."""
    return f"telemetry/{TELEMETRY_CACHE_REVISION}/{year}/{gp}/{session}/_complete-v2.json"


def valid_race_pace(data):
    """Reject empty or malformed timing indexes so they can be rebuilt."""
    if not isinstance(data, dict) or safe_float(data.get("TotalLaps")) <= 0:
        return False
    drivers = data.get("Drivers")
    if not isinstance(drivers, dict) or not drivers:
        return False
    for driver in drivers.values():
        if not isinstance(driver, dict):
            return False
        laps = driver.get("Laps")
        if not isinstance(laps, list) or not laps:
            return False
        if any(not isinstance(lap, dict)
               or safe_float(lap.get("LapNumber")) <= 0
               or safe_float(lap.get("LapTime")) <= 0 for lap in laps):
            return False
    return True


def read_circuit_corners(data):
    """Read legacy lists and expiring unavailable-map records; None is a miss."""
    if isinstance(data, dict):
        if data.get("Corners") != [] or safe_float(data.get("RetryAfter")) <= time.time():
            return None
        return []
    if not isinstance(data, list) or not data:
        return None
    for corner in data:
        if (not isinstance(corner, dict)
                or safe_float(corner.get("Number")) <= 0
                or safe_float(corner.get("Distance"), -1) < 0
                or not isinstance(corner.get("Letter"), str)):
            return None
    return data


def circuit_corners_payload(corners):
    """Retry missing optional maps after one day instead of on every request."""
    return corners if corners else {"Corners": [], "RetryAfter": time.time() + 86400}

def get_r2_client():
    if not all([R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        return None
    try:
        return boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4", connect_timeout=10,
                          read_timeout=30, retries={"max_attempts": 2})
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
        try:
            return json.loads(response['Body'].read().decode('utf-8'))
        finally:
            response['Body'].close()
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
            Body=json.dumps(sanitized, allow_nan=False),
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
        if e.response['Error']['Code'] not in ('NoSuchKey', '404', 'NotFound'):
            raise
        return False

