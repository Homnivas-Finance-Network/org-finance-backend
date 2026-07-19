import io
import json
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from firebase_admin import firestore
from openai import OpenAI
from pypdf import PdfReader

from app.config import settings
from app.database import db
from app.auth import get_verified_uid

router = APIRouter(prefix="/api/analytics", tags=["AI Engine"])

# OpenRouter exposes an OpenAI-compatible endpoint — same client, different base_url.
ai_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=settings.OPENROUTER_API_KEY)

MAX_FILE_BYTES = 8 * 1024 * 1024  # 8MB per PDF

# OpenRouter's free tier (":free" model IDs) is gated by REQUEST count
# (20/min, 50-1000/day depending on whether you've ever topped up $10),
# not by tokens-per-minute. A single long-document call is fine as long
# as it fits the model's context window. Still capped below to keep
# cost/latency sane and leave headroom under whichever context window
# the current OPENROUTER_MODEL actually has.
CIBIL_CHAR_LIMIT = 20000
BANK_CHAR_LIMIT = 60000

SYSTEM_PROMPT = """
You are a strict financial analysis engine. Output ONLY raw JSON matching this exact structure, nothing else, no markdown code fences, no commentary:
{
  "arthScore": (number 0-100),
  "actualCibil": (number),
  "monthlySalary": (number),
  "totalCurrentEmi": (number),
  "debtReductionRoadmap": ["step 1", "step 2"],
  "chartData": {"emis": number, "livingExpenses": number, "savings": number},
  "ELIGIBLE_FOR_1_EMI": (boolean, true ONLY if actualCibil >= 650),
  "fdSignalDetected": (boolean, true if the bank statement shows FD interest credits, TDS on interest, or term deposit related entries),
  "estimatedFDValue": (number or null, rough estimate from interest credit amounts if detectable, else null)
}
"""


def extract_pdf_text(file_bytes: bytes, password: Optional[str] = None) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            if not password:
                raise ValueError("This PDF is password protected. Please provide the password.")
            if not reader.decrypt(password):
                raise ValueError("Incorrect PDF password.")
        return "".join(page.extract_text() or "" for page in reader.pages)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not read PDF: {e}")


async def _read_and_validate(file: UploadFile) -> bytes:
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=422, detail=f"{file.filename} must be a PDF")
    raw = await file.read()
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=422, detail=f"{file.filename} exceeds 8MB")
    return raw


def _parse_json_response(raw_text: str) -> dict:
    """Free models on OpenRouter don't all honor response_format={"type": "json_object"}
    strictly — some wrap the JSON in a ```json fence or add a stray sentence
    before/after it. Try clean parsing first, then fall back to extracting
    the outermost {...} block before giving up."""
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip("` \n")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise ValueError("Model did not return parseable JSON")


def _call_ai(cibil_text: str, bank_text: str, retries: int = 1) -> dict:
    """OpenRouter's free tier is best-effort shared capacity — it can 429 or
    time out during peak hours. One retry with a short backoff covers most
    transient failures without making the user wait too long behind a
    loading screen that already says 10-20s."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = ai_client.chat.completions.create(
                model=settings.OPENROUTER_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"CIBIL:\n{cibil_text}\n\nBANK:\n{bank_text}"},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                extra_headers={
                    # Optional but recommended by OpenRouter for routing/analytics attribution
                    "HTTP-Referer": settings.APP_URL,
                    "X-Title": "Homnivas Finance Pro",
                },
            )
            return _parse_json_response(response.choices[0].message.content)
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2)
                continue
    raise last_error


@router.post("/analyze")
async def analyze_finances(
    pdfPassword: Optional[str] = Form(None),
    cibilPdf: UploadFile = File(...),
    bankStatementPdf: UploadFile = File(...),
    uid: str = Depends(get_verified_uid),
):
    user_ref = db.collection("users").document(uid)
    user_doc = user_ref.get()

    if not user_doc.exists or not user_doc.to_dict().get("isPro", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Payment required")

    cibil_raw = await _read_and_validate(cibilPdf)
    bank_raw = await _read_and_validate(bankStatementPdf)

    try:
        cibil_text = extract_pdf_text(cibil_raw)[:CIBIL_CHAR_LIMIT]
        bank_text = extract_pdf_text(bank_raw, password=pdfPassword)[:BANK_CHAR_LIMIT]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        analysis_data = _call_ai(cibil_text, bank_text)
    except Exception as e:
        # Surfaced distinctly so the frontend can show "AI is busy, try again in a
        # minute" instead of a generic error.
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {e}")

    run_ref = user_ref.collection("analysisRuns").document()
    run_ref.set({**analysis_data, "createdAt": firestore.SERVER_TIMESTAMP})

    user_ref.set(
        {
            "latestAnalysisId": run_ref.id,
            "status": "ANALYZED",
            "eligibility": {
                "oneEmi": {
                    "eligible": analysis_data.get("ELIGIBLE_FOR_1_EMI", False),
                    "checkedAt": firestore.SERVER_TIMESTAMP,
                },
                "loanAgainstFD": {
                    "eligible": analysis_data.get("fdSignalDetected", False),
                    "checkedAt": firestore.SERVER_TIMESTAMP,
                },
            },
            "journey": {"completedSteps": firestore.ArrayUnion(["ANALYSIS_COMPLETED"])},
        },
        merge=True,
    )

    return {**analysis_data, "analysisId": run_ref.id}


@router.post("/eligibility/loan-against-fd/self-declare")
async def declare_fd(declaredAmount: float = Form(...), uid: str = Depends(get_verified_uid)):
    """Fallback for FDs held elsewhere that won't show as interest credits in the
    uploaded bank statement. Shown on the dashboard when fdSignalDetected is false."""
    db.collection("users").document(uid).set(
        {
            "eligibility": {
                "loanAgainstFD": {
                    "eligible": True,
                    "selfDeclared": True,
                    "declaredAmount": declaredAmount,
                    "checkedAt": firestore.SERVER_TIMESTAMP,
                }
            }
        },
        merge=True,
    )
    return {"status": "recorded"}
