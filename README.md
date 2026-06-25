# Vigour Seeds WhatsApp Agent Backend — Phase 1

This repository houses the production WhatsApp automation backend for **Vigour Seeds** (an Indian agri seed company). The agent runs 24x7 to communicate with farmers and distributors in Hindi/Hinglish.

This is **Phase 1** of development: Scaffold, health checks, webhook verification handshake, and Docker/Render setup.

---

## Technical Stack
*   **Language/Framework**: Python 3.12 + FastAPI + Uvicorn
*   **Containerization**: Docker
*   **Deployment**: Render (web service + future cron worker)
*   **Testing**: pytest

---

## Local Setup & Development

1.  **Clone and Navigate**:
    ```bash
    cd "vigour seeds"
    ```

2.  **Virtual Environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Environment Variables**:
    Copy `.env.example` to `.env` and fill in your details:
    ```bash
    cp .env.example .env
    ```

4.  **Run Locally**:
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ```

---

## Verification & Testing

### Automated Tests
Run the pytest test suite:
```bash
PYTHONPATH=. pytest tests/
```

### Regression Tests
Run the complete regression test suites to guarantee all past features remain intact:
```bash
PYTHONPATH=. ./venv/bin/pytest tests/test_conversations.py
PYTHONPATH=. ./venv/bin/pytest tests/test_agent_regression.py
```
These suites cover onboarding priority, direct seed requests, available crop list queries, crop switches, no-product crop fallback handling, safety locks, off-topic classifications, image upload polite refusal, and fabricated-product post-reply safeguards completely offline.

**Crucial Deployment Checklist**:
- You **MUST** run the full test suite (`PYTHONPATH=. ./venv/bin/pytest`) and ensure all tests are green before pushing any code to GitHub.
- If any test fails, it means a past behavior broke — **fix it** before pushing.
- CI on GitHub Actions must be green before deploying.

### Docker Verification
Build and run the container locally:
```bash
docker build -t vigour-seeds-backend .
docker run -p 8000:8000 \
  -e META_VERIFY_TOKEN=my_verify_token \
  -e META_WHATSAPP_TOKEN=token \
  -e META_PHONE_NUMBER_ID=phone_id \
  -e META_APP_SECRET=app_secret \
  -e SUPABASE_URL=url \
  -e SUPABASE_SERVICE_KEY=key \
  vigour-seeds-backend
```
Then verify health:
```bash
curl http://localhost:8000/health
```
And verify webhook handshake:
```bash
curl "http://localhost:8000/webhook?hub.mode=subscribe&hub.verify_token=my_verify_token&hub.challenge=12345"
```
