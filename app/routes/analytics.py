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

MAX_FILE_BYTES = 13 * 1024 * 1024  # 13MB per PDF
# Cloud Run has a hard 32MB limit on the TOTAL request body — platform-level,
# not configurable in app code. Two files at 13MB + multipart boundary/header
# overhead stays safely under that. Do not raise this without also solving
# the Cloud Run ceiling (e.g. direct-to-Cloud-Storage signed URL upload
# instead of sending the file through this endpoint) — otherwise larger
# files just get a 413 from the platform before this code ever runs.

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
  "cibilHolderName": (string, the full name printed on the CIBIL report, exactly as written),
  "bankHolderName": (string, the full name printed on the bank statement / account holder name, exactly as written),
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

arthScore must weigh THREE things, not just CIBIL: (1) credit history (CIBIL), (2) EMI burden as a fraction of income, (3) savings rate as a fraction of income. A high CIBIL with zero or near-zero savings and EMIs+expenses consuming all income is a FRAGILE position, not a strong one — do not score it above 60 regardless of CIBIL. Reserve 80+ for cases with genuine savings headroom, not just a clean credit history.
"""


def normalize_name(name: str) -> set:
    """Loose tokenization for name comparison — strips punctuation/titles,
    lowercases, drops short tokens (initials, "Mr", "Shri" etc.)."""
    if not name:
        return set()
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", name).lower()
    stopwords = {"mr", "mrs", "ms", "shri", "smt", "dr"}
    return {tok for tok in cleaned.split() if len(tok) > 1 and tok not in stopwords}


def names_plausibly_match(name_a: str, name_b: str) -> bool:
    """Deterministic check, not left to the model's own judgment — names are
    security-relevant here, so this runs in Python against the model's
    extracted fields rather than trusting a model-reported "do these match"
    boolean. Tolerant of middle names / name-order differences, but requires
    real evidence: a single shared token (often just a common first name
    like "Amit") isn't enough on its own when both names have a surname to
    compare too — "Amit Patel" and "Amit Kumar Shah" must NOT pass just
    because they share "Amit". Extraction failures (empty name on either
    side) don't block — that's an OCR/extraction quality problem, not
    evidence of a mismatch, and shouldn't punish the user for it."""
    tokens_a = normalize_name(name_a)
    tokens_b = normalize_name(name_b)
    if not tokens_a or not tokens_b:
        return True
    overlap = tokens_a & tokens_b
    smaller = min(len(tokens_a), len(tokens_b))
    if smaller == 1:
        return len(overlap) >= 1
    return len(overlap) >= 2 or len(overlap) == smaller


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
    cibilPassword: Optional[str] = Form(None),
    bankPassword: Optional[str] = Form(None),
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
        cibil_text = extract_pdf_text(cibil_raw, password=cibilPassword)[:CIBIL_CHAR_LIMIT]
        bank_text = extract_pdf_text(bank_raw, password=bankPassword)[:BANK_CHAR_LIMIT]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        analysis_data = _call_ai(cibil_text, bank_text)
    except Exception as e:
        # Surfaced distinctly so the frontend can show "AI is busy, try again in a
        # minute" instead of a generic error.
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {e}")

    if not names_plausibly_match(
        analysis_data.get("cibilHolderName", ""), analysis_data.get("bankHolderName", "")
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "The name on your CIBIL report doesn't match the name on your bank "
                "statement. Please make sure both documents belong to the same person."
            ),
        )

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


@router.get("/history")
async def get_history(uid: str = Depends(get_verified_uid)):
    """Every /analyze call already gets saved to analysisRuns — this just
    exposes that as a time series for the Home tab's score history chart."""
    runs = (
        db.collection("users")
        .document(uid)
        .collection("analysisRuns")
        .order_by("createdAt")
        .limit(24)
        .stream()
    )
    history = []
    for run in runs:
        data = run.to_dict()
        created_at = data.get("createdAt")
        history.append(
            {
                "id": run.id,
                "arthScore": data.get("arthScore"),
                "actualCibil": data.get("actualCibil"),
                "createdAt": created_at.isoformat() if created_at else None,
            }
        )
    return {"history": history}


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


ADVISOR_SYSTEM_PROMPT = """
You are Arth, a calm and direct personal finance advisor for an Indian user.
You have their real financial analysis below — use it specifically, don't give
generic advice. Keep answers under 120 words, plain language, no jargon unless
you define it. You are not a licensed financial advisor and cannot recommend
specific loans, stocks, or insurance products by name — you can explain
tradeoffs and point them to what to consider.
"""


@router.post("/ask")
async def ask_advisor(question: str = Form(...), uid: str = Depends(get_verified_uid)):
    """Step 9's 'Ask Arth anything' — grounded in the user's actual latest
    analysis, not a generic chatbot. Requires a completed /analyze run first."""
    user_doc = db.collection("users").document(uid).get()
    if not user_doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user_data = user_doc.to_dict()
    analysis_id = user_data.get("latestAnalysisId")
    if not analysis_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run an analysis first — upload your CIBIL report and bank statement.",
        )

    analysis_doc = (
        db.collection("users").document(uid).collection("analysisRuns").document(analysis_id).get()
    )
    analysis_data = analysis_doc.to_dict() if analysis_doc.exists else {}

    context = (
        f"Arth Score: {analysis_data.get('arthScore')}\n"
        f"CIBIL: {analysis_data.get('actualCibil')}\n"
        f"Monthly salary: {analysis_data.get('monthlySalary')}\n"
        f"Total current EMI: {analysis_data.get('totalCurrentEmi')}\n"
        f"Debt reduction roadmap: {analysis_data.get('debtReductionRoadmap')}\n"
        f"Chart data: {analysis_data.get('chartData')}\n"
        f"Eligible for 1-EMI consolidation: {analysis_data.get('ELIGIBLE_FOR_1_EMI')}\n"
    )

    try:
        response = _call_ai_simple(context, question)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Advisor is busy, try again shortly: {e}")

    return {"answer": response}


def _call_ai_simple(context: str, question: str, retries: int = 1) -> str:
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = ai_client.chat.completions.create(
                model=settings.OPENROUTER_MODEL,
                messages=[
                    {"role": "system", "content": ADVISOR_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Financial data:\n{context}\n\nQuestion: {question}"},
                ],
                temperature=0.4,
                extra_headers={"HTTP-Referer": settings.APP_URL, "X-Title": "Homnivas Finance Pro"},
            )
            return response.choices[0].message.content
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2)
                continue
    raise last_error
