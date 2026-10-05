import os
from dotenv import load_dotenv

load_dotenv()
import uuid

try:
    import boto3
except ImportError:
    boto3 = None


def r2_configured():
    required = [
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "R2_ENDPOINT_URL",
        "R2_PUBLIC_URL",
    ]

    return all(os.getenv(key) for key in required)


def get_r2_client():
    if boto3 is None:
        raise RuntimeError("boto3 haijawekwa. Run: pip install boto3")

    if not r2_configured():
        raise RuntimeError(
            "Cloudflare R2 environment variables hazijawekwa."
        )

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    )


def get_public_url(key):
    base_url = os.getenv("R2_PUBLIC_URL", "").rstrip("/")
    return f"{base_url}/{key.lstrip('/')}"


def upload_file(file_obj, folder):
    if not file_obj or not file_obj.filename:
        raise ValueError("Hakuna file iliyochaguliwa.")

    if not r2_configured():
        raise RuntimeError(
            "Cloudflare R2 environment variables hazijawekwa."
        )

    original_name = file_obj.filename
    extension = os.path.splitext(original_name)[1].lower()

    if not extension:
        raise ValueError("File haina extension.")

    key = f"{folder.strip('/')}/{uuid.uuid4().hex}{extension}"

    client = get_r2_client()

    client.upload_fileobj(
        file_obj,
        os.getenv("R2_BUCKET_NAME"),
        key,
        ExtraArgs={
            "ContentType": file_obj.content_type
            or "application/octet-stream"
        },
    )

    return get_public_url(key)
