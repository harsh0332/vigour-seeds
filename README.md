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
Run the specific conversation-level regression test suite:
```bash
PYTHONPATH=. pytest tests/test_conversations.py
```
This suite covers core user interactions, agent flows, intent classifications, and product recommendation safeguards completely offline. It is highly recommended to run this suite before pushing any code changes or deploying to staging/production.

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
