import json

from google.cloud import storage
from google.oauth2 import service_account

from app.config import settings

if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
    _creds_dict = json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
    _credentials = service_account.Credentials.from_service_account_info(_creds_dict)
else:
    # Local dev only — same fallback pattern as database.py
    _credentials = service_account.Credentials.from_service_account_file("service-account.json")

storage_client = storage.Client(credentials=_credentials, project=_credentials.project_id)
bucket = storage_client.bucket(settings.FIREBASE_STORAGE_BUCKET)


def generate_upload_url(blob_path: str, content_type: str = "application/pdf", expiry_minutes: int = 15) -> str:
    """V4 signed URL, PUT method — the browser uploads directly to this URL,
    the request never touches Cloud Run, so its 32MB body limit doesn't
    apply. Signing happens locally with the service account's private key
    (no extra IAM permission needed beyond what Firestore access already
    requires)."""
    from datetime import timedelta

    blob = bucket.blob(blob_path)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=expiry_minutes),
        method="PUT",
        content_type=content_type,
    )
