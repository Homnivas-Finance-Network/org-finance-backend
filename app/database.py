import json

import firebase_admin
from firebase_admin import credentials, firestore

from app.config import settings

if not firebase_admin._apps:
    if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
        # Production: Cloud Run env var / Secret Manager holds the full JSON as a string
        cred_dict = json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
        cred = credentials.Certificate(cred_dict)
    else:
        # Local dev: keep service-account.json in the project root (already in .gitignore)
        cred = credentials.Certificate("service-account.json")

    firebase_admin.initialize_app(cred)

db = firestore.client()
