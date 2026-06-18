import os
import json
import logging
import requests
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Body
from fastapi.middleware.cors import CORSMiddleware
import firebase_admin
from firebase_admin import credentials, firestore, auth

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Homnivas Finance Network API",
    description="Backend engine powering AI loan extraction, tracking, and partner operations.",
    version="1.0.0"
)

# Configure CORS
# In production, replace "*" with your exact PWA domain (e.g., "https://partner.homnivas.space")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Safe Firebase Admin SDK Initialization
if not firebase_admin._apps:
    try:
        # For Google Cloud Run production environment (uses default service account)
        firebase_admin.initialize_app()
        logger.info("Firebase Admin initialized successfully via Application Default Credentials.")
    except Exception as e:
        logger.warning(f"Default Firebase initialization skipped/failed: {e}")
        # Local development fallback
        service_account_path = "serviceAccountKey.json"
        if os.path.exists(service_account_path):
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin initialized successfully via local serviceAccountKey.json.")
        else:
            logger.critical("Firebase Admin could not be initialized. Check credential configurations.")

db = firestore.client()

@app.get("/")
def read_root():
    """Health check endpoint to ensure the container is alive and listening."""
    return {
        "status": "healthy",
        "organization": "Homnivas Finance Network",
        "service": "Core Python AI Engine"
    }

@app.post("/api/chat")
async def chat_with_ai(
    user_message: str = Body(..., embed=True), 
    broker_id: str = Body(..., embed=True),
    language: Optional[str] = Body("en", embed=True)
):
    """
    Main chat terminal for brokers. Integrates with OpenRouter AI 
    to process loan inquiries, parse pasted data blocks, and guide document workflow.
    """
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_api_key:
        logger.error("Missing OPENROUTER_API_KEY environment variable.")
        raise HTTPException(status_code=500, detail="Internal server configuration error.")
        
    # Injecting the master platform persona into the system instructions
    system_prompt = (
        "You are 'Homnivas Loan Finance Manager', a premium, highly intelligent financial AI assistant operating "
        "as a digital branch manager for Homnivas Finance Network. Your primary job is to assist outskirt loan partners "
        "and brokers in West Bengal to onboard files seamlessly.\n\n"
        
        "CRITICAL RULES:\n"
        "1. TONE: Warm, encouraging, entrepreneurial, professional, and accessible to a layman.\n"
        "2. LANGUAGES: Fully fluent in English, Bengali, and Hindi. Always detect the user's input language/dialect "
        "and reply to them using that exact linguistic comfort zone (including conversational code-switching like 'Benglish' or 'Hinglish').\n"
        "3. DATA CAPTURE: Look out for key data points: Client Name, Income, Loan Type (Home, Personal, Business, Mortgage), "
        "and Employment Type. If the broker copy-pastes a chaotic chunk of text or a WhatsApp forward containing client details, "
        "do not ask redundant questions. Process what is there, confirm the parameters beautifully like a clean summary table, "
        "and politely request only the missing pieces or document pictures (PAN card, bank statement, etc.).\n"
        "4. SUPPORT: If the user asks about platform operations or payouts, guide them cleanly on how to use their "
        "PWA dashboard tabs ('My Clients' 5-stage visual tracker or 'Wealth' request cash-out section)."
    )
    
    headers = {
        "Authorization": f"Bearer {openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://homnivas.space", # Identifies your app traffic to OpenRouter
        "X-Title": "Homnivas Finance Network"
    }
    
    payload = {
        # Using Gemini 1.5 Flash via OpenRouter for blazing fast, low-cost multimodal/text execution
        "model": "google/gemini-flash-1.5", 
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.3 # Low temperature keeps financial configurations accurate and grounded
    }
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions", 
            headers=headers, 
            data=json.dumps(payload),
            timeout=30
        )
        
        if response.status_code != 200:
            logger.error(f"OpenRouter API error response: {response.text}")
            raise HTTPException(status_code=502, detail="Upstream AI provider communication error.")
            
        response_data = response.json()
        ai_reply = response_data['choices'][0]['message']['content']
        return {"reply": ai_reply}
        
    except requests.exceptions.Timeout:
        logger.error("Timeout connecting to OpenRouter API.")
        raise HTTPException(status_code=504, detail="AI response timed out. Please try again.")
    except Exception as e:
        logger.error(f"Unhandled exception in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server runtime breakdown.")
