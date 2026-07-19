from fastapi import Request, HTTPException, status
from firebase_admin import auth

# Import triggers Firebase Admin init (see database.py) before auth.verify_id_token is used
from app import database  # noqa: F401


async def get_verified_uid(request: Request) -> str:
    """
    Verifies the Firebase ID token sent by the frontend as:
        Authorization: Bearer <idToken>
    Returns the caller's real, verified Firebase UID.

    Never trust a userId passed in a request body or form field —
    that lets anyone impersonate anyone else by guessing/copying a UID.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = header.split(" ", 1)[1]
    try:
        decoded = auth.verify_id_token(token)
        return decoded["uid"]
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
