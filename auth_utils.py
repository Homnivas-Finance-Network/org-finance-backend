"""
Firebase Authentication helper.

Brokers sign in on the PWA using Firebase Auth (email/password). The PWA
attaches the broker's ID token as `Authorization: Bearer <token>` on every
API call. This module verifies that token server-side so a broker can never
read or write another broker's cases just by guessing a case_id.
"""

import logging
from fastapi import Header, HTTPException
from firebase_admin import auth as firebase_auth

logger = logging.getLogger(__name__)


async def get_current_broker(authorization: str = Header(None)) -> dict:
    """
    FastAPI dependency. Verifies the Firebase ID token sent in the
    Authorization header and returns the decoded token (contains at least
    `uid` and usually `email`).

    Raises 401 if the header is missing/malformed or the token is invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header. Expected 'Bearer <Firebase ID token>'.",
        )

    id_token = authorization.split("Bearer ", 1)[1].strip()

    try:
        decoded = firebase_auth.verify_id_token(id_token)
        return decoded
    except firebase_auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    except Exception as e:
        logger.error(f"Auth verification failed: {e}")
        raise HTTPException(status_code=401, detail="Could not verify authentication token.")
