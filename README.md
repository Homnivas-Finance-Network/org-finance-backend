# Homnivas Finance Pro — Backend

FastAPI backend for the 10-step (now 11-step) flow: free quiz → ₹345 paywall →
CIBIL/bank statement analysis via OpenRouter → Debt Avalanche dashboard →
1-EMI consolidation and Loan-Against-FD lead handoff to NBFC partners.

```
app/
  main.py          FastAPI app + CORS + router registration
  config.py        All env vars, one place
  database.py      Firebase Admin / Firestore init
  auth.py          Verifies Firebase ID tokens on every protected route
  routes/
    payments.py    Razorpay order creation + webhook (Step 5)
    analytics.py   PDF parsing + OpenRouter analysis + eligibility (Steps 7-9)
    leads.py       NBFC handoff for 1-EMI and Loan-Against-FD (Steps 10-11)
Dockerfile
requirements.txt
.env.example
```

Everything below assumes you're deploying the way you already do: build from
GitHub via the Cloud Run **console** (not gcloud CLI), frontend on Cloudflare
Pages.

---

## 1. Firebase — Auth + Firestore

1. [console.firebase.google.com](https://console.firebase.google.com) → create a project (or use your existing `ohmaya-ai`-style project, but keep this **separate** from Maya — don't mix Homnivas user data into the same Firebase project as an unrelated internal tool).
2. **Build → Authentication → Get started** → enable **Phone** sign-in (Step 1 of the flow).
3. **Build → Firestore Database → Create database** → start in **production mode** (not test mode — test mode leaves your DB open to anyone for 30 days).
4. Get the backend's admin credentials: **Project Settings (gear icon) → Service Accounts → Generate New Private Key**. This downloads a `.json` file.
   - **Do not commit this file.** It's already excluded via `.gitignore` and `.dockerignore`.
   - Locally: rename it `service-account.json`, drop it in the project root, leave `FIREBASE_SERVICE_ACCOUNT_JSON` blank in `.env`.
   - In production: open the file, copy its entire contents, and paste them as **one line** into the `FIREBASE_SERVICE_ACCOUNT_JSON` variable in Cloud Run (Section 4 below).

Firestore security rules matter even though your frontend won't read/write
most of this data directly (it all goes through your FastAPI backend using
the admin SDK, which bypasses rules entirely). But if your frontend ever
reads anything directly from Firestore with the client SDK (e.g. live-listening
to `users/{uid}` for a real-time dashboard), lock it down:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /users/{userId} {
      allow read: if request.auth != null && request.auth.uid == userId;
      allow write: if false; // only the backend (admin SDK) writes
    }
  }
}
```

---

## 2. Razorpay — payment gate (Step 5)

1. [dashboard.razorpay.com](https://dashboard.razorpay.com) → sign up as a business, complete KYC (needed before you can go live — start this early, it can take a few days).
2. Start in **Test mode** (toggle top-left). **Settings → API Keys → Generate Test Key** → copy `Key Id` and `Key Secret` into `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`.
3. Set up the webhook:
   - **Account & Settings → Webhooks → + Add New Webhook**
   - **URL**: your Cloud Run URL + `/api/payments/webhook` (you'll have this after Section 4 — come back to this step)
   - **Secret**: type a new random string here yourself (this is deliberately a *different* secret from your API key secret — that's correct, keep them separate). Put this value in `RAZORPAY_WEBHOOK_SECRET`.
   - **Active events**: check `payment.captured` and `payment.failed`
   - Save.
4. When you're ready for real money: complete KYC, toggle to **Live mode**, generate **Live** API keys, and repeat step 3 for a live-mode webhook (test and live webhooks are configured separately). Swap the env vars in Cloud Run — don't reuse test keys in production.

---

## 3. OpenRouter — AI analysis engine (Steps 8-9)

Using OpenRouter's free tier specifically because your documents are long.
It caps by **request count**, not tokens-per-minute (20/min, 50/day unfunded
or 1,000/day after a one-time, non-expiring $10 top-up) — so a 15K-token
document call costs the same "1 request" as a 500-token one.

1. [openrouter.ai/keys](https://openrouter.ai/keys) → sign up, no card needed → **Create Key** → put it in `OPENROUTER_API_KEY`.
2. Default model is `openrouter/free` in `config.py` — OpenRouter's own auto-router, which picks whichever currently-free model matches the request's needs. **This isn't theoretical: `meta-llama/llama-3.3-70b-instruct:free` (the original pin) was repriced to paid-only in the field**, breaking `/analyze` with a 404 until the model was switched. The auto-router exists specifically to survive that. If you'd rather pin a named model anyway (more consistent behavior, less uptime resilience), check [openrouter.ai/models](https://openrouter.ai/models) filtered to Price: Free for current options, and update `OPENROUTER_MODEL` in Cloud Run — no code change needed, it's an env var.
3. **Worth doing on day one**: deposit $10 once (never expires, doesn't need to stay in your balance) to move from 50 to 1,000 free requests/day. At ₹345/analysis-eligible customer, 50/day will feel tight fast; $10 one-time removes that ceiling for a long while.
4. **Reliability trade-off you're accepting**: free tier is best-effort shared capacity — it can slow down or 429 during peak hours, and the auto-router can pick a different underlying model between calls (fine for structured JSON extraction, worth knowing if output tone/style ever needs to feel consistent). `analytics.py` already retries once with a short backoff and returns a distinct error the frontend can show as "AI is busy, try again shortly." If reliability becomes a real problem at volume, the fix is a paid OpenRouter model (one line: change `OPENROUTER_MODEL` to a specific paid slug) — not a full provider migration.
5. Free models don't all honor strict JSON-mode reliably. `_parse_json_response()` in `analytics.py` handles this — strips markdown fences and falls back to extracting the outermost `{...}` block if a model wraps its answer in extra text.

---

## 4. Google Cloud Run — deploy the backend

### First-time setup
1. Push this repo to GitHub (private repo — it contains no secrets since `.env` and `service-account.json` are gitignored, but keep it private anyway).
2. [console.cloud.google.com/run](https://console.cloud.google.com/run) → **Create Service** → **Continuously deploy from a repository** → connect GitHub → select this repo → branch `main`.
3. Build type: **Dockerfile** (it's in the repo root, Cloud Run will detect it automatically).
4. Region: `asia-south1` (Mumbai) — lowest latency for Indian users and keeps you compliant with data-locality expectations for a lending-adjacent product.
5. Authentication: **Allow unauthenticated invocations** (your API does its own auth via Firebase tokens per-route, not Cloud Run's IAM layer).

### Environment variables — all of it, as plain Variables
On the same create/edit screen: **Container(s) → Variables & Secrets tab → Variables → + Add Variable**. Add every one of these directly — no Secret Manager step:
```
PLATFORM_FEE=345
OPENROUTER_MODEL=openrouter/free
ENVIRONMENT=production
ALLOWED_ORIGINS=https://yourfrontend.pages.dev
APP_URL=https://finance.homnivas.space

RAZORPAY_KEY_ID=rzp_live_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxx
RAZORPAY_WEBHOOK_SECRET=xxxxxxxxxxxxxxxxxxxx
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxx
FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"...", ...}
```
`FIREBASE_SERVICE_ACCOUNT_JSON` is the entire downloaded JSON file pasted as one line — the Cloud Run variable value field accepts long strings fine, just make sure there are no line breaks in what you paste.

One thing to know since you're skipping Secret Manager: plain Variables are visible in full, in plain text, to anyone with read access to the Cloud Run service (console, `gcloud run services describe`, or your IAM-permissioned teammates later). For a solo project right now that's a fine tradeoff for the simplicity. If you ever add a second person with console access, or this account handles meaningfully more money, move the four sensitive ones (`RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `OPENROUTER_API_KEY`, `FIREBASE_SERVICE_ACCOUNT_JSON`) into Secret Manager — same field names, just referenced instead of typed in, and it's a 10-minute change whenever you want it.

### Wire the webhook URL
Once deployed, copy the Cloud Run service URL (looks like `https://homnivas-finance-pro-xxxxx.a.run.app`), go back to Razorpay's webhook settings (Section 2, step 3), and set the URL to `<that-url>/api/payments/webhook`.

### Custom domain (optional, for production)
Cloud Run service → **Manage Custom Domains** → map e.g. `api.homnivas.space` → follow the DNS verification steps shown. Update `ALLOWED_ORIGINS` and Razorpay's webhook URL to match if you do this.

---

## 5. Frontend — Cloudflare Pages

Same as your existing workflow: connect the frontend repo, set the build
output directory, and add one env var pointing it at your Cloud Run API base
URL. Make sure the frontend attaches the Firebase ID token as
`Authorization: Bearer <token>` on every call to `/api/payments/*`,
`/api/analytics/*`, and `/api/leads/*` — those routes will 401 without it.

---

## 6. Go-live checklist

- [ ] Firestore is in production mode with rules deployed, not left in test mode
- [ ] Razorpay KYC complete, live keys generated, live webhook configured and tested with a real ₹1 test transaction
- [ ] OpenRouter $10 top-up done (or you've confirmed the 50/day free cap comfortably covers real launch volume — test with an actual dense 6-month statement, not a short sample)
- [ ] All env vars set in Cloud Run, `.env` and `service-account.json` confirmed absent from the GitHub repo (`git log --all -- .env service-account.json` should return nothing)
- [ ] `ALLOWED_ORIGINS` set to your real production frontend domain, not `*`
- [ ] Webhook URL in Razorpay points at the live Cloud Run URL, not a dev/staging one
- [ ] Basic uptime/error monitoring on the Cloud Run service (Cloud Run's built-in **Logs** and **Metrics** tabs are enough to start — don't need a third-party tool on day one)
