from fastapi import APIRouter, Depends, Form
from firebase_admin import firestore

from app.database import db
from app.auth import get_verified_uid

router = APIRouter(prefix="/api/profile", tags=["Profile"])


@router.post("/setup")
async def setup_profile(
    name: str = Form(...),
    pan: str = Form(...),
    city: str = Form(...),
    employmentType: str = Form(...),
    monthlySalary: float = Form(...),
    uid: str = Depends(get_verified_uid),
):
    """Step 6. Only reachable meaningfully after payment, but not gated on
    isPro — profile details themselves aren't a paid feature, and gating
    would just add friction with nothing paid protecting."""
    db.collection("users").document(uid).set(
        {
            "profile": {
                "name": name,
                "pan": pan.upper(),
                "city": city,
                "employmentType": employmentType,
                "monthlySalary": monthlySalary,
            },
            "journey": {"completedSteps": firestore.ArrayUnion(["PROFILE_COMPLETED"])},
        },
        merge=True,
    )
    return {"status": "saved"}


@router.get("/me")
async def get_profile(uid: str = Depends(get_verified_uid)):
    """Lets the frontend pre-fill the profile form and check isPro/eligibility
    state on load, instead of re-deriving it from scattered local state."""
    doc = db.collection("users").document(uid).get()
    if not doc.exists:
        return {"exists": False}
    return {"exists": True, **doc.to_dict()}
