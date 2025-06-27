# backend/storage_backends.py
from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class MinIOStorage(S3Boto3Storage):
    """
    Custom storage backend for MinIO to generate URLs with '/minio' prefix.
    """

    bucket_name = "exam"  # default bucket

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.custom_domain = getattr(settings, "MINIO_EXTERNAL_DOMAIN", "10.10.0.2")
        self.url_protocol = "http:"

    def url(self, name, parameters=None, expire=None, http_method=None):
        """
        Generate URL with external domain and '/asset' prefix.
        """
        # Get the base URL from parent class
        url = super().url(name, parameters, expire, http_method)

        if not url:
            return url

        # Replace internal docker endpoint with external domain
        url = url.replace("http://minio:9000", f"http://{self.custom_domain}")

        # Parse the URL to extract the path
        if "://" in url:
            protocol, rest = url.split("://", 1)
            if "/" in rest:
                domain_part, path_part = rest.split("/", 1)
                # Reconstruct URL with custom domain and ensure /asset prefix
                if not path_part.startswith("asset/"):
                    path_part = f"asset/{path_part}"
                url = f"http://{self.custom_domain}/{path_part}"
            else:
                # No path part, just domain
                url = f"http://{self.custom_domain}/asset/"

        return url

    def _normalize_name(self, name):
        return super()._normalize_name(name)

    def get_available_name(self, name, max_length=None):
        return super().get_available_name(name, max_length)
