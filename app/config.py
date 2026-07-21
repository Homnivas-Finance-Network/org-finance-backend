from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Razorpay
    RAZORPAY_KEY_ID: str
    RAZORPAY_KEY_SECRET: str
    RAZORPAY_WEBHOOK_SECRET: str  # separate secret set on the Razorpay Webhooks dashboard page, NOT your API key secret
    PLATFORM_FEE: int = 345  # rupees

    # OpenRouter — free tier, request-count limited rather than token-limited,
    # which fits long bank statement / CIBIL PDFs well.
    # Default is OpenRouter's own auto-router: it picks whichever currently-free
    # model matches the request's needs (e.g. structured JSON output), so it
    # survives individual free models being repriced or pulled. Pin to a named
    # model instead only if you need consistent behavior more than uptime —
    # check openrouter.ai/models filtered to Price: Free for current options.
    OPENROUTER_API_KEY: str
    OPENROUTER_MODEL: str = "openrouter/free"
    APP_URL: str  # sent as HTTP-Referer to OpenRouter, cosmetic only — set to your real domain

    # Firebase — paste the full service account JSON as one line into this env var in production.
    # Leave empty locally and keep a service-account.json file in the project root instead (gitignored).
    FIREBASE_SERVICE_ACCOUNT_JSON: str = ""

    ENVIRONMENT: str = "production"

    # DANGER: when true, ANY authenticated user can grant themselves Pro
    # without paying via POST /api/payments/dev-grant-pro. Only ever set
    # this to true in a local/dev Cloud Run env var during testing — never
    # in the production service. Defaults off so a forgotten deploy is safe.
    ALLOW_DEV_BYPASS: bool = False

    # comma-separated list of frontend origins allowed to call this API
    ALLOWED_ORIGINS: str

    class Config:
        env_file = ".env"


settings = Settings()
