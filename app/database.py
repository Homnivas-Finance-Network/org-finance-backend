import json

import firebase_admin
from firebase_admin import credentials, firestore

from app.config import settings

if not firebase_admin._apps:
    try:
        if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
            # Production: Cloud Run env var holds the full JSON as a string
            cred_dict = json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
            cred = credentials.Certificate(cred_dict)
        else:
            # Local dev ONLY: keep service-account.json in the project root (gitignored).
            # This file does not exist in the deployed container — if this line runs
            # on Cloud Run, FIREBASE_SERVICE_ACCOUNT_JSON was never set there.
            cred = credentials.Certificate("service-account.json")
    except json.JSONDecodeError as e:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON is set but is not valid JSON. Re-copy the "
            "entire downloaded service account key file as one unbroken line into the "
            f"Cloud Run variable. Original error: {e}"
        ) from e
    except FileNotFoundError as e:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON is missing or empty, and there's no local "
            "service-account.json in this container (expected — it's gitignored). "
            "In Cloud Run: Edit & Deploy New Revision > Container(s) > Variables & "
            "Secrets tab > Variables > add FIREBASE_SERVICE_ACCOUNT_JSON with the full "
            "contents of your Firebase service account key file."
        ) from e

    firebase_admin.initialize_app(cred)

db = firestore.client()
