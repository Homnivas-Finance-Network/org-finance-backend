from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Razorpay
    RAZORPAY_KEY_ID: str
    RAZORPAY_KEY_SECRET: str
    RAZORPAY_WEBHOOK_SECRET: str  # separate secret set on the Razorpay Webhooks dashboard page, NOT your API key secret
    PLATFORM_FEE: int = 345  # rupees

    # OpenRouter — free tier, request-count limited rather than token-limited,
    # which fits long bank statement / CIBIL PDFs well.
    # Free model list rotates on OpenRouter without much notice — if OPENROUTER_MODEL
    # starts 404ing, check openrouter.ai/models filtered to Price: Free and swap this.
    OPENROUTER_API_KEY: str
    OPENROUTER_MODEL: str = "meta-llama/llama-3.3-70b-instruct:free"
    APP_URL: str = "https://finance.homnivas.space/"  # sent as HTTP-Referer to OpenRouter, cosmetic only

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
    ALLOWED_ORIGINS: str = "https://finance.homnivas.space, https://org-finance-pwa.pages.dev"

    class Config:
        env_file = ".env"


settings = Settings()
