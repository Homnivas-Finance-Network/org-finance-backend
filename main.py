import os
import json
import requests
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import firebase_admin
from firebase_admin import credentials, firestore, auth

app = FastAPI(title="Homnivas Finance API")

# Enable CORS so your PWA (partner.homnivas.space) can securely talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Change this to your exact PWA domain later for production security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Firebase Admin SDK
# When running on Cloud Run, it can automatically inherit permissions if configured, 
# or you can load a service account JSON file.
if not firebase_admin._apps:
    cred = credentials.ApplicationDefault() # Inherits Google Cloud Project credentials automatically
    firebase_admin.initialize_app(cred, {
        'storageBucket': 'YOUR_PROJECT_ID.appspot.com' # Replace with your Firebase storage bucket name
    })

db = firestore.client()

@app.get("/")
def read_root():
    return {"status": "Homnivas Finance Backend is Running"}

@app.post("/api/chat")
async def chat_with_ai(user_message: str, broker_id: str):
    """
    Receives text from the broker PWA, injects business logic context, 
    and returns a response from OpenRouter AI.
    """
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_api_key:
        raise HTTPException(status_code=500, detail="OpenRouter API Key missing on server configuration.")
        
    # 1. Fetch system prompt rules (You can store this rule sheet in Firestore!)
    system_prompt = (
        "You are 'Homnivas Finance Network', a premium, highly smart AI assistant for loan brokers in West Bengal. "
        "Your tone is warm, encouraging, helpful, and professional. Speak in English, Bengali, or Hindi based on user preference. "
        "Help them extract client data for Home, Personal, Business, and Mortgage loans. "
        "Analyze text fields or copy-pasted data to look for Name, Income, Loan Amount, and Profession."
    )
    
    # 2. Structure the payload for OpenRouter
    headers = {
        "Authorization": f"Bearer {openrouter_api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "meta-llama/llama-3-8b-instruct:free", # You can upgrade to Claude/Gemini flash models later easily
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
    }
    
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, data=json.dumps(payload))
        response_data = response.json()
        ai_reply = response_data['choices'][0]['message']['content']
        return {"reply": ai_reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
