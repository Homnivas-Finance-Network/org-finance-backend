import os
import re
import json
import logging
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Body, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import io

import firebase_admin
from firebase_admin import credentials, firestore

from schemas import FIELD_SCHEMAS, VERTICAL_NAMES, flat_fields, valid_keys, progress
from auth_utils import get_current_broker
from pdf_gen import generate_infosheet_pdf

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Homnivas Finance Network API",
    description="Backend engine powering AI loan-data extraction, case tracking, infosheet PDFs, and partner operations.",
    version="2.0.0",
)

# CORS — set CORS_ALLOWED_ORIGINS to a comma-separated list of your live
# Firebase Hosting domain(s) in the Cloud Run environment variables, e.g.
#   CORS_ALLOWED_ORIGINS=https://homnivas-finance.web.app,https://partner.homnivas.space
# Falls back to "*" only if unset, so existing deployments keep working
# until you set it — but you should set it before going further into production.
_origins_env = os.getenv("CORS_ALLOWED_ORIGINS")
if _origins_env:
    ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]
else:
    logger.warning(
        "CORS_ALLOWED_ORIGINS is not set — allowing all origins ('*'). "
        "Set this Cloud Run env var to your Firebase Hosting domain(s) before production use."
    )
    ALLOWED_ORIGINS = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Safe Firebase Admin SDK Initialization
if not firebase_admin._apps:
    try:
        firebase_admin.initialize_app()
        logger.info("Firebase Admin initialized successfully via Application Default Credentials.")
    except Exception as e:
        logger.warning(f"Default Firebase initialization skipped/failed: {e}")
        service_account_path = "serviceAccountKey.json"
        if os.path.exists(service_account_path):
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin initialized successfully via local serviceAccountKey.json.")
        else:
            logger.critical("Firebase Admin could not be initialized. Check credential configurations.")

db = firestore.client()

CASES_COLLECTION = "cases"
BROKERS_COLLECTION = "brokers"

# Comma-separated list of email addresses allowed to sign in via Google as
# Homnivas staff/admin, e.g. "ops@homnivas.space,founder@homnivas.space"
# Set this in Cloud Run env vars. Anyone else attempting Google sign-in is
# rejected — only phone OTP is open to the public (partners/brokers).
ADMIN_EMAILS = {
    e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()
}

STAGE_LABELS = {
    1: "New Lead",
    2: "Document Collection",
    3: "Verification",
    4: "Sanctioned",
    5: "Disbursed",
}

DATA_BLOCK_RE = re.compile(r"\[\[DATA\]\](.*?)\[\[/DATA\]\]", re.DOTALL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_owned_case(case_id: str, broker_uid: str) -> dict:
    """Fetch a case and verify the requesting broker owns it. Returns the doc dict (with id)."""
    doc_ref = db.collection(CASES_COLLECTION).document(case_id)
    snap = doc_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Case not found.")
    case = snap.to_dict()
    if case.get("brokerId") != broker_uid:
        raise HTTPException(status_code=403, detail="You do not have access to this case.")
    case["id"] = snap.id
    return case


def _get_broker_profile(uid: str) -> Optional[dict]:
    snap = db.collection(BROKERS_COLLECTION).document(uid).get()
    if not snap.exists:
        return None
    profile = snap.to_dict()
    profile["uid"] = uid
    return profile


def _determine_role(decoded_token: dict) -> str:
    """
    Decide whether the authenticated user is a 'partner' (signed in via phone
    OTP — open to anyone) or 'admin' (signed in via Google — restricted to
    ADMIN_EMAILS). Raises 403 if a Google sign-in isn't on the allowlist.
    """
    provider = decoded_token.get("firebase", {}).get("sign_in_provider", "")

    if provider == "phone":
        return "partner"

    if provider == "google.com":
        email = (decoded_token.get("email") or "").lower()
        if not email or email not in ADMIN_EMAILS:
            raise HTTPException(
                status_code=403,
                detail="This Google account isn't authorized for Homnivas employee access.",
            )
        return "admin"

    raise HTTPException(status_code=403, detail="Unsupported sign-in method.")


def _build_system_prompt(vertical: str, existing_data: dict, language: str) -> str:
    vertical_label = VERTICAL_NAMES.get(vertical, vertical)
    fields = flat_fields(vertical)

    checklist_lines = []
    for key, label, section in fields:
        val = str(existing_data.get(key, "")).strip()
        status = f"ALREADY HAVE: \"{val}\"" if val else "STILL NEEDED"
        checklist_lines.append(f"- [{key}] {label} ({section}) — {status}")
    checklist = "\n".join(checklist_lines)

    return (
        "You are 'Homnivas Loan Finance Manager', a premium, highly intelligent financial AI assistant operating "
        "as a digital branch manager for Homnivas Finance Network. Your primary job is to assist outskirt loan partners "
        "and brokers in West Bengal to onboard files seamlessly.\n\n"

        f"CURRENT CASE VERTICAL: {vertical_label} ({vertical})\n\n"

        "CRITICAL RULES:\n"
        "1. TONE: Warm, encouraging, entrepreneurial, professional, and accessible to a layman.\n"
        "2. LANGUAGES: Fully fluent in English, Bengali, and Hindi. Always detect the user's input language/dialect "
        "and reply to them using that exact linguistic comfort zone (including conversational code-switching like 'Benglish' or 'Hinglish'). "
        f"The broker's last selected language preference is '{language}', but always prioritize what they actually type in.\n"
        "3. DATA CAPTURE: This case needs the following fields filled in. If the broker pastes a chaotic chunk of text or a "
        "WhatsApp forward containing client details, do not ask redundant questions — extract what's there. Otherwise, ask "
        "for 2-4 missing fields at a time, grouped naturally by topic (don't interrogate one field per message). Once a field "
        "is captured, never ask for it again unless the broker is clearly correcting it.\n"
        "4. SUPPORT: If the user asks about platform operations or payouts, guide them cleanly on how to use their "
        "PWA dashboard tabs ('Clients' 5-stage visual tracker or 'Wallet' cash-out section).\n"
        "5. When all or nearly all fields are captured, tell the broker the infosheet is ready and they can generate the "
        "PDF from the case's detail screen.\n\n"

        "FIELD CHECKLIST FOR THIS CASE:\n"
        f"{checklist}\n\n"

        "OUTPUT FORMAT — FOLLOW EXACTLY:\n"
        "First write your natural conversational reply to the broker (in their language, as normal chat text).\n"
        "Then, on a new line at the very end of your message, append a hidden machine-readable block containing ONLY "
        "the fields you can confidently extract or correct from THIS message exchange (do not repeat fields you're not "
        "newly updating). Use the exact bracketed key names from the checklist above as JSON keys. If nothing new was "
        "captured, output an empty object. This block is stripped out before the broker ever sees it — never mention it, "
        "never explain it, never wrap it in extra text or markdown fences. Format exactly like this:\n"
        "[[DATA]]{\"field_key\": \"value\"}[[/DATA]]"
    )


def _extract_data_block(ai_text: str):
    """Split the AI reply into (clean_reply_text, extracted_fields_dict)."""
    match = DATA_BLOCK_RE.search(ai_text)
    if not match:
        return ai_text.strip(), {}

    clean_text = (ai_text[: match.start()] + ai_text[match.end():]).strip()

    raw_json = match.group(1).strip()
    try:
        parsed = json.loads(raw_json)
        if not isinstance(parsed, dict):
            parsed = {}
    except (json.JSONDecodeError, TypeError):
        logger.warning("Could not parse AI data block as JSON; ignoring extraction for this turn.")
        parsed = {}

    return clean_text, parsed


def _call_openrouter(system_prompt: str, recent_messages: list, user_message: str) -> str:
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_api_key:
        logger.error("Missing OPENROUTER_API_KEY environment variable.")
        raise HTTPException(status_code=500, detail="Internal server configuration error.")

    headers = {
        "Authorization": f"Bearer {openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://homnivas.space",
        "X-Title": "Homnivas Finance Network",
    }

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(recent_messages)
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": "openrouter/free",
        "messages": messages,
        "temperature": 0.3,
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            data=json.dumps(payload),
            timeout=30,
        )
        if response.status_code != 200:
            logger.error(f"OpenRouter API error response: {response.text}")
            raise HTTPException(status_code=502, detail="Upstream AI provider communication error.")

        response_data = response.json()
        return response_data["choices"][0]["message"]["content"]

    except requests.exceptions.Timeout:
        logger.error("Timeout connecting to OpenRouter API.")
        raise HTTPException(status_code=504, detail="AI response timed out. Please try again.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unhandled exception calling OpenRouter: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server runtime breakdown.")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/")
def read_root():
    """Health check endpoint to ensure the container is alive and listening."""
    return {
        "status": "healthy",
        "organization": "Homnivas Finance Network",
        "service": "Core Python AI Engine",
        "verticals": list(VERTICAL_NAMES.keys()),
    }


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@app.get("/api/schema/{vertical}")
def get_schema(vertical: str, broker=Depends(get_current_broker)):
    vertical = vertical.upper()
    if vertical not in FIELD_SCHEMAS:
        raise HTTPException(status_code=404, detail="Unknown vertical.")
    sections = [
        {"section": title, "fields": [{"key": k, "label": l} for k, l in fields]}
        for title, fields in FIELD_SCHEMAS[vertical]
    ]
    return {"vertical": vertical, "label": VERTICAL_NAMES[vertical], "sections": sections}


@app.get("/api/verticals")
def get_verticals():
    return {"verticals": [{"code": k, "label": v} for k, v in VERTICAL_NAMES.items()]}


# ---------------------------------------------------------------------------
# Broker profile (name capture + role determination)
# ---------------------------------------------------------------------------

@app.get("/api/profile")
def get_profile(broker=Depends(get_current_broker)):
    profile = _get_broker_profile(broker["uid"])
    if not profile:
        return {"exists": False}
    return {
        "exists": True,
        "uid": profile["uid"],
        "name": profile.get("name", ""),
        "role": profile.get("role", "partner"),
        "phone": profile.get("phone", ""),
        "email": profile.get("email", ""),
    }


@app.post("/api/profile")
def create_or_update_profile(
    name: str = Body(..., embed=True),
    broker=Depends(get_current_broker),
):
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty.")

    role = _determine_role(broker)  # raises 403 for unauthorized Google sign-ins

    profile_ref = db.collection(BROKERS_COLLECTION).document(broker["uid"])
    existing = profile_ref.get()

    payload = {
        "name": name,
        "role": role,
        "phone": broker.get("phone_number", ""),
        "email": broker.get("email", ""),
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    if not existing.exists:
        payload["createdAt"] = firestore.SERVER_TIMESTAMP

    profile_ref.set(payload, merge=True)

    return {
        "exists": True,
        "uid": broker["uid"],
        "name": name,
        "role": role,
        "phone": payload["phone"],
        "email": payload["email"],
    }


# ---------------------------------------------------------------------------
# Case management
# ---------------------------------------------------------------------------

@app.post("/api/cases")
def create_case(
    vertical: str = Body(..., embed=True),
    client_name: Optional[str] = Body(None, embed=True),
    broker=Depends(get_current_broker),
):
    vertical = vertical.upper()
    if vertical not in FIELD_SCHEMAS:
        raise HTTPException(status_code=400, detail=f"Unknown vertical '{vertical}'. Must be one of {list(FIELD_SCHEMAS.keys())}.")

    initial_data = {}
    if client_name:
        initial_data["name"] = client_name

    doc_ref = db.collection(CASES_COLLECTION).document()
    doc_ref.set({
        "brokerId": broker["uid"],
        "brokerEmail": broker.get("email", ""),
        "brokerPhone": broker.get("phone_number", ""),
        "vertical": vertical,
        "status": 1,
        "data": initial_data,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })

    return {
        "case_id": doc_ref.id,
        "vertical": vertical,
        "status": 1,
        "stage_label": STAGE_LABELS[1],
        "progress": progress(vertical, initial_data),
    }


@app.get("/api/cases")
def list_cases(broker=Depends(get_current_broker)):
    query = (
        db.collection(CASES_COLLECTION)
        .where("brokerId", "==", broker["uid"])
        .order_by("updatedAt", direction=firestore.Query.DESCENDING)
        .limit(200)
    )
    results = []
    for snap in query.stream():
        case = snap.to_dict()
        data = case.get("data", {})
        vertical = case.get("vertical", "PL")
        results.append({
            "case_id": snap.id,
            "vertical": vertical,
            "vertical_label": VERTICAL_NAMES.get(vertical, vertical),
            "client_name": data.get("name") or "New Lead",
            "status": case.get("status", 1),
            "stage_label": STAGE_LABELS.get(case.get("status", 1), "New Lead"),
            "progress": progress(vertical, data),
            "updated_at": case.get("updatedAt"),
        })
    return {"cases": results}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, broker=Depends(get_current_broker)):
    case = _get_owned_case(case_id, broker["uid"])
    vertical = case.get("vertical", "PL")
    data = case.get("data", {})

    messages_query = (
        db.collection(CASES_COLLECTION).document(case_id)
        .collection("messages")
        .order_by("createdAt")
        .limit(100)
    )
    messages = [
        {"role": m.to_dict().get("role"), "text": m.to_dict().get("text")}
        for m in messages_query.stream()
    ]

    return {
        "case_id": case_id,
        "vertical": vertical,
        "vertical_label": VERTICAL_NAMES.get(vertical, vertical),
        "status": case.get("status", 1),
        "stage_label": STAGE_LABELS.get(case.get("status", 1), "New Lead"),
        "data": data,
        "progress": progress(vertical, data),
        "messages": messages,
    }


@app.patch("/api/cases/{case_id}/data")
def update_case_data(
    case_id: str,
    fields: dict = Body(..., embed=True),
    broker=Depends(get_current_broker),
):
    case = _get_owned_case(case_id, broker["uid"])
    vertical = case.get("vertical", "PL")
    allowed_keys = valid_keys(vertical)

    sanitized = {f"data.{k}": str(v) for k, v in fields.items() if k in allowed_keys}
    if not sanitized:
        raise HTTPException(status_code=400, detail="No valid fields supplied for this vertical.")

    sanitized["updatedAt"] = firestore.SERVER_TIMESTAMP
    db.collection(CASES_COLLECTION).document(case_id).update(sanitized)

    updated_snap = db.collection(CASES_COLLECTION).document(case_id).get()
    updated_data = updated_snap.to_dict().get("data", {})
    return {"case_id": case_id, "data": updated_data, "progress": progress(vertical, updated_data)}


@app.patch("/api/cases/{case_id}/status")
def update_case_status(
    case_id: str,
    status: int = Body(..., embed=True),
    broker=Depends(get_current_broker),
):
    if status not in STAGE_LABELS:
        raise HTTPException(status_code=400, detail=f"status must be one of {list(STAGE_LABELS.keys())}.")
    _get_owned_case(case_id, broker["uid"])
    db.collection(CASES_COLLECTION).document(case_id).update({
        "status": status,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    return {"case_id": case_id, "status": status, "stage_label": STAGE_LABELS[status]}


# ---------------------------------------------------------------------------
# Chat (AI data capture)
# ---------------------------------------------------------------------------

@app.post("/api/chat")
async def chat_with_ai(
    case_id: str = Body(..., embed=True),
    user_message: str = Body(..., embed=True),
    language: Optional[str] = Body("en", embed=True),
    broker=Depends(get_current_broker),
):
    """
    Main chat turn for a case. Sends the broker's message to the AI along with
    the case's current vertical checklist, then merges any newly-extracted
    fields straight into Firestore.
    """
    case = _get_owned_case(case_id, broker["uid"])
    vertical = case.get("vertical", "PL")
    existing_data = case.get("data", {})

    # Light recent context (last 3 turns) so replies feel continuous without
    # re-sending the whole transcript every time — the real "memory" lives in
    # the structured case data above, not the chat log.
    history_query = (
        db.collection(CASES_COLLECTION).document(case_id)
        .collection("messages")
        .order_by("createdAt", direction=firestore.Query.DESCENDING)
        .limit(6)
    )
    recent = [m.to_dict() for m in history_query.stream()]
    recent.reverse()
    recent_messages = [
        {"role": "user" if m.get("role") == "user" else "assistant", "content": m.get("text", "")}
        for m in recent
    ]

    system_prompt = _build_system_prompt(vertical, existing_data, language)
    ai_raw_reply = _call_openrouter(system_prompt, recent_messages, user_message)
    clean_reply, extracted_fields = _extract_data_block(ai_raw_reply)

    allowed_keys = valid_keys(vertical)
    sanitized_fields = {k: str(v).strip() for k, v in extracted_fields.items() if k in allowed_keys and str(v).strip()}

    case_ref = db.collection(CASES_COLLECTION).document(case_id)

    # Persist chat turn
    msgs_ref = case_ref.collection("messages")
    msgs_ref.add({"role": "user", "text": user_message, "createdAt": firestore.SERVER_TIMESTAMP})
    msgs_ref.add({"role": "assistant", "text": clean_reply, "createdAt": firestore.SERVER_TIMESTAMP})

    merged_data = dict(existing_data)
    if sanitized_fields:
        merged_data.update(sanitized_fields)
        update_payload = {f"data.{k}": v for k, v in sanitized_fields.items()}
        update_payload["updatedAt"] = firestore.SERVER_TIMESTAMP
        case_ref.update(update_payload)
    else:
        case_ref.update({"updatedAt": firestore.SERVER_TIMESTAMP})

    return {
        "reply": clean_reply,
        "case_id": case_id,
        "updated_fields": list(sanitized_fields.keys()),
        "progress": progress(vertical, merged_data),
    }


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

@app.post("/api/cases/{case_id}/pdf")
def generate_pdf(case_id: str, broker=Depends(get_current_broker)):
    case = _get_owned_case(case_id, broker["uid"])
    vertical = case.get("vertical", "PL")
    data = case.get("data", {})
    client_label = data.get("name") or "New Lead"

    profile = _get_broker_profile(broker["uid"])
    broker_name = (profile and profile.get("name")) or broker.get("phone_number") or broker.get("email", "")

    pdf_bytes = generate_infosheet_pdf(vertical, case_id, broker_name, client_label, data)

    filename = f"Homnivas-{vertical}-{client_label.replace(' ', '_')}-{case_id[:6]}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
