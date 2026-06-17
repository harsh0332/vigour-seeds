import os
import hmac
import hashlib
import json
import pytest

# Set mock environment variables before importing app
os.environ["META_VERIFY_TOKEN"] = "test_verify_token"
os.environ["META_WHATSAPP_TOKEN"] = "test_whatsapp_token"
os.environ["META_PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_service_key"
os.environ["APP_ENV"] = "production"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_webhook_get_verify_success():
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "test_verify_token",
        "hub.challenge": "12345678"
    }
    response = client.get("/webhook", params=params)
    assert response.status_code == 200
    assert response.text == "12345678"

def test_webhook_get_verify_failure_wrong_token():
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong_token",
        "hub.challenge": "12345678"
    }
    response = client.get("/webhook", params=params)
    assert response.status_code == 403

def test_webhook_get_verify_failure_invalid_mode():
    params = {
        "hub.mode": "invalid_mode",
        "hub.verify_token": "test_verify_token",
        "hub.challenge": "12345678"
    }
    response = client.get("/webhook", params=params)
    assert response.status_code == 403

def test_webhook_post_success():
    payload = {"object": "whatsapp_business_account", "entry": []}
    payload_bytes = json.dumps(payload).encode("utf-8")
    
    # Calculate signature
    app_secret = "test_app_secret".encode("utf-8")
    signature = hmac.new(app_secret, payload_bytes, hashlib.sha256).hexdigest()
    
    headers = {
        "X-Hub-Signature-256": f"sha256={signature}",
        "Content-Type": "application/json"
    }
    
    response = client.post("/webhook", content=payload_bytes, headers=headers)
    assert response.status_code == 200
    assert response.text == "EVENT_RECEIVED"

def test_webhook_post_failure_bad_signature():
    payload = {"object": "whatsapp_business_account", "entry": []}
    payload_bytes = json.dumps(payload).encode("utf-8")
    
    headers = {
        "X-Hub-Signature-256": "sha256=invalid_signature",
        "Content-Type": "application/json"
    }
    
    response = client.post("/webhook", content=payload_bytes, headers=headers)
    assert response.status_code == 403

def test_webhook_post_failure_missing_signature():
    payload = {"object": "whatsapp_business_account", "entry": []}
    payload_bytes = json.dumps(payload).encode("utf-8")
    
    response = client.post("/webhook", content=payload_bytes)
    assert response.status_code == 403
