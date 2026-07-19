from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore
from pydantic import BaseModel

from app.database import db
from app.auth import get_verified_uid

router = APIRouter(prefix="/api/leads", tags=["Leads"])

# Different products usually go to different NBFC partners — unsecured PL
# consolidation and secured Loan-Against-FD are rarely the same lender.
# Replace these with your actual partner identifiers/API endpoints once signed.
NBFC_ROUTES = {
    "ONE_EMI": "partner_unsecured_pl",
    "LOAN_AGAINST_FD": "partner_secured_laf",
}


class LeadRequest(BaseModel):
    productType: str  # "ONE_EMI" or "LOAN_AGAINST_FD"
    declaredFDAmount: Optional[float] = None


@router.post("/submit")
async def submit_lead(payload: LeadRequest, uid: str = Depends(get_verified_uid)):
    if payload.productType not in NBFC_ROUTES:
        raise HTTPException(status_code=400, detail="Unknown productType")

    user_ref = db.collection("users").document(uid)
    user_doc = user_ref.get()
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    data = user_doc.to_dict()
    elig = data.get("eligibility", {})

    if payload.productType == "ONE_EMI" and not elig.get("oneEmi", {}).get("eligible"):
        raise HTTPException(status_code=400, detail="Not eligible for 1-EMI consolidation")

    if payload.productType == "LOAN_AGAINST_FD" and not (
        elig.get("loanAgainstFD", {}).get("eligible") or payload.declaredFDAmount
    ):
        raise HTTPException(status_code=400, detail="No FD signal detected or declared")

    lead_ref = db.collection("leads").document()
    lead_ref.set(
        {
            "userId": uid,
            "productType": payload.productType,
            "nbfcPartner": NBFC_ROUTES[payload.productType],
            "declaredFDAmount": payload.declaredFDAmount,
            "status": "SUBMITTED",
            "createdAt": firestore.SERVER_TIMESTAMP,
            "latestAnalysisId": data.get("latestAnalysisId"),
        }
    )

    user_ref.set(
        {"journey": {"completedSteps": firestore.ArrayUnion([f"LEAD_SUBMITTED_{payload.productType}"])}},
        merge=True,
    )

    # TODO: call the actual NBFC partner API here once you have credentials —
    # package cibil/bank-derived fields from analysisRuns/{latestAnalysisId}
    # rather than re-asking the user for anything.

    return {"leadId": lead_ref.id, "status": "SUBMITTED"}
