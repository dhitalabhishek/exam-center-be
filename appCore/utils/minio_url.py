import os

import boto3
from botocore.client import Config


def generate_presigned_minio_url(object_name, expires_in=3600):
    session = boto3.session.Session()
    s3_client = session.client(
        "s3",
        endpoint_url=os.getenv("AWS_S3_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",  # MinIO doesn't enforce region
    )

    try:
        response = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": os.getenv("AWS_STORAGE_BUCKET_NAME"), "Key": object_name},
            ExpiresIn=expires_in,
        )
    except Exception as e:  # noqa: BLE001
        print("Error generating pre-signed URL:", e)  # noqa: T201
        return None

    return response
