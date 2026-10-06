import logging
import boto3
from botocore.config import Config
from django.conf import settings

logger = logging.getLogger(__name__)


def get_presigned_url(field_file, expiration: int = 3600) -> str:
    """
    Generate a short-lived pre-signed URL for secure Proof-of-Delivery assets
    stored in AWS S3 or Cloudflare R2.

    Falls back to the standard media URL when using local FileSystemStorage
    or if cloud storage credentials are not actively configured.
    """
    if not field_file or not getattr(field_file, "name", None):
        return ""

    use_s3 = getattr(settings, "USE_S3", False)
    bucket_name = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)

    if use_s3 and bucket_name:
        access_key = getattr(settings, "AWS_ACCESS_KEY_ID", None)
        secret_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", None)
        region_name = getattr(settings, "AWS_S3_REGION_NAME", "auto")
        endpoint_url = getattr(settings, "AWS_S3_ENDPOINT_URL", None) or None

        try:
            s3_client = boto3.client(
                "s3",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region_name,
                endpoint_url=endpoint_url,
                config=Config(signature_version="s3v4"),
            )
            return s3_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket_name,
                    "Key": field_file.name,
                },
                ExpiresIn=expiration,
            )
        except Exception as exc:
            logger.warning("Failed to generate pre-signed URL for %s: %s", field_file.name, exc)

    try:
        return field_file.url
    except Exception:
        return ""
