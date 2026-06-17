import os
import sys
import pytest
from datetime import datetime
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock, AsyncMock

# 1. Pre-set dummy environment variables for configuration
os.environ["META_VERIFY_TOKEN"] = "test_verify_token"
os.environ["META_WHATSAPP_TOKEN"] = "test_whatsapp_token"
os.environ["META_PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_service_key"
os.environ["AI_PROVIDER"] = "gemini"
os.environ["GEMINI_API_KEY"] = "mock_gemini_key"
os.environ["ALERT_CHANNEL"] = "log"

# --- Mock Response Class ---
class MockResponse:
    def __init__(self, data):
        self.data = data

# --- InMemory Database State ---
class InMemoryDB:
    def __init__(self):
        self.clear_all()

    def clear_all(self):
        self.tables = {
            "sessions": [],
            "leads_farmer": [],
            "leads_distributor_new": [],
            "tickets": [],
            "conversations": [],
            "distributors_active": [],
            "recommendation_rules": [],
            "regions": [],
            "products": [],
            "crops": []
        }

    def seed_defaults(self):
        # 1. Regions
        self.tables["regions"] = [
            {
                "region_id": 1,
                "state": "Madhya Pradesh",
                "state_code": "MP",
                "is_active": "Y",
                "nearest_depot": "Indore Depot",
                "sales_rep_name": "Rajesh Kumar",
                "sales_rep_phone": "917777777777",
                "agronomist_name": "Dr. Ramesh",
                "agronomist_phone": "916666666666"
            }
        ]
        # 2. Crops
        self.tables["crops"] = [
            {"crop_id": "CR01", "crop_name_hi": "सोयाबीन", "crop_name_en": "Soybean", "in_catalog": "Y"}
        ]
        # 3. Recommendation Rules
        self.tables["recommendation_rules"] = [
            {
                "rule_id": "R002",
                "crop": "Soybean",
                "crop_stage": "sowing",
                "problem_category": "-",
                "irrigation_type": "Rainfed/Irrigated",
                "region": "MP",
                "recommended_product_ids": "PROD_S1, PROD_S2",
                "next_action": "send_recommendation",
                "human_review_required": False
            },
            {
                "rule_id": "R003",
                "crop": "Soybean",
                "crop_stage": "sowing",
                "problem_category": "pest_attack",
                "irrigation_type": "Rainfed/Irrigated",
                "region": "MP",
                "recommended_product_ids": "PROD_S1",
                "next_action": "send_recommendation",
                "human_review_required": False
            }
        ]
        # 4. Products
        self.tables["products"] = [
            {
                "product_id": "PROD_S1",
                "variety_name": "Vigour 335",
                "crop": "Soybean",
                "duration_days": "95",
                "mrp_inr": 150.0,
                "key_traits": "उच्च उपज",
                "pest_disease_tolerance": "tolerant",
                "pack_size": "20 kg",
                "approved_for_recommendation": "Y",
                "target_region": "MP"
            },
            {
                "product_id": "PROD_S2",
                "variety_name": "Vigour 9560",
                "crop": "Soybean",
                "duration_days": "90",
                "mrp_inr": 180.0,
                "key_traits": "कम समय",
                "pest_disease_tolerance": "tolerant",
                "pack_size": "20 kg",
                "approved_for_recommendation": "Y",
                "target_region": "MP"
            }
        ]
        # 5. Distributors
        self.tables["distributors_active"] = [
            {
                "distributor_id": "DST001",
                "whatsapp_phone": "918888888888",
                "contact_name": "Sanjay Sharma",
                "shop_name": "Sharma Seeds",
                "state": "MP",
                "district": "Ujjain",
                "territory_code": "TERR01",
                "onboarded_date": "2025-01-01",
                "assigned_sales_rep": "Rajesh Kumar",
                "assigned_sales_rep_phone": "917777777777",
                "active_status": "active"
            },
            {
                "distributor_id": "DST002",
                "whatsapp_phone": "918888888889",
                "contact_name": "Dealer Two",
                "shop_name": "District Seeds",
                "state": "MP",
                "district": "Indore",
                "territory_code": "TERR01",
                "onboarded_date": "2025-01-01",
                "assigned_sales_rep": "Rajesh Kumar",
                "assigned_sales_rep_phone": "917777777777",
                "active_status": "active"
            }
        ]

    def insert_row(self, table: str, data: dict) -> dict:
        row = dict(data)
        if "created_at" not in row:
            row["created_at"] = datetime.utcnow().isoformat() + "Z"
        self.tables[table].append(row)
        return row

    def delete_row(self, table: str, row: dict):
        if row in self.tables[table]:
            self.tables[table].remove(row)

    def get_rows(self, table: str, filters: list) -> list:
        matched = []
        for row in self.tables[table]:
            match = True
            for field, op, val in filters:
                if op == "eq":
                    if row.get(field) != val:
                        match = False
                        break
                elif op == "ilike":
                    val_str = str(row.get(field) or "").lower()
                    if str(val).lower() not in val_str:
                        match = False
                        break
            if match:
                matched.append(row)
        return matched

in_memory_db = InMemoryDB()

# --- Mock Supabase Table Reference Builder ---
class InMemoryTable:
    def __init__(self, name: str, db: InMemoryDB):
        self.name = name
        self.db = db
        self.filters = []
        self.order_by = None
        self.limit_val = None
        self.is_delete = False
        self.insert_data = None
        self.update_data = None

    def select(self, fields="*"):
        return self

    def eq(self, field, value):
        if self.name == "distributors_active" and field == "state":
            if value == "Madhya Pradesh":
                value = "MP"
        self.filters.append((field, "eq", value))
        return self

    def ilike(self, field, pattern):
        pattern_cleaned = pattern.replace("%", "").lower()
        self.filters.append((field, "ilike", pattern_cleaned))
        return self

    def order(self, field, desc=False):
        self.order_by = (field, desc)
        return self

    def limit(self, val):
        self.limit_val = val
        return self

    def delete(self):
        self.is_delete = True
        return self

    def insert(self, data):
        self.insert_data = data
        return self

    def update(self, data):
        self.update_data = data
        return self

    def execute(self):
        if self.insert_data is not None:
            data = self.insert_data
            if isinstance(data, list):
                res_list = [self.db.insert_row(self.name, d) for d in data]
                return MockResponse(res_list)
            else:
                res = self.db.insert_row(self.name, data)
                return MockResponse([res])

        if self.update_data is not None:
            rows = self.db.get_rows(self.name, self.filters)
            for r in rows:
                r.update(self.update_data)
                r["updated_at"] = datetime.utcnow().isoformat() + "Z"
            return MockResponse(rows)

        if self.is_delete:
            rows = list(self.db.get_rows(self.name, self.filters))
            for r in rows:
                self.db.delete_row(self.name, r)
            return MockResponse(rows)

        rows = list(self.db.get_rows(self.name, self.filters))
        if self.order_by:
            field, desc = self.order_by
            rows.sort(key=lambda x: str(x.get(field, "")), reverse=desc)
        if self.limit_val is not None:
            rows = rows[:self.limit_val]
        return MockResponse(rows)

class InMemorySupabaseClient:
    def __init__(self, db: InMemoryDB):
        self.db = db
        self.storage = MagicMock()
        
        # Mock storage bucket behavior
        bucket_mock = MagicMock()
        bucket_mock.upload = MagicMock(return_value=True)
        bucket_mock.get_public_url = MagicMock(side_effect=lambda f: f"https://mock.supabase.co/storage/v1/object/public/crop-photos/{f}")
        self.storage.from_ = MagicMock(return_value=bucket_mock)
        
        bucket_obj = MagicMock()
        bucket_obj.name = "crop-photos"
        self.storage.list_buckets = MagicMock(return_value=[bucket_obj])

    def table(self, table_name: str) -> InMemoryTable:
        return InMemoryTable(table_name, self.db)

# Instantiate the mock Supabase Client
mock_supabase_client = InMemorySupabaseClient(in_memory_db)

# --- Mock WhatsApp Client ---
class MockWhatsAppClient:
    def __init__(self):
        self.sent_messages = []

    def clear(self):
        self.sent_messages.clear()

    async def send_text(self, to: str, body: str) -> dict:
        self.sent_messages.append({"to": to, "type": "text", "body": body})
        return {"messages": [{"id": f"msg_{len(self.sent_messages)}"}]}

    async def send_buttons(self, to: str, body: str, buttons: list) -> dict:
        self.sent_messages.append({"to": to, "type": "buttons", "body": body, "buttons": buttons})
        return {"messages": [{"id": f"msg_{len(self.sent_messages)}"}]}

    async def send_list(self, to: str, header: str, body: str, sections: list) -> dict:
        self.sent_messages.append({"to": to, "type": "list", "header": header, "body": body, "sections": sections})
        return {"messages": [{"id": f"msg_{len(self.sent_messages)}"}]}

    async def send_template(self, to: str, template_name: str, components: list) -> dict:
        self.sent_messages.append({"to": to, "type": "template", "template_name": template_name, "components": components})
        return {"messages": [{"id": f"msg_{len(self.sent_messages)}"}]}

    async def download_media(self, media_id: str) -> tuple:
        return b"mock_media_bytes", "image/jpeg"

mock_whatsapp_client = MockWhatsAppClient()

# --- Mock AI Provider ---
class MockAIProvider:
    def __init__(self):
        self.should_fail = False

    async def complete(
        self,
        system: str,
        user: str,
        images: Optional[List[Dict[str, Any]]] = None,
        json_mode: bool = False
    ) -> str:
        from app.core.errors import ai_circuit_breaker, AICircuitBreakerOpenException
        from app.services.metrics import metrics_service
        
        if self.should_fail:
            ai_circuit_breaker.record_failure()
            metrics_service.increment_ai_errors()
            raise Exception("Simulated AI Failure")

        if not ai_circuit_breaker.allow_request():
            metrics_service.increment_ai_errors()
            raise AICircuitBreakerOpenException("AI provider circuit breaker is OPEN")

        ai_circuit_breaker.record_success()

        # 1. Intent Classifier Mocking
        if "intent classifier" in system.lower():
            text = user.lower()
            intent = "general_inquiry"
            if "कीड़े" in text or "pest" in text or "disease" in text or "बीमारी" in text or "photo" in text:
                intent = "farmer_crop_problem"
            elif "distributor" in text or "डीलर" in text or "firm" in text:
                intent = "distributor_new"
            elif "payment" in text or "billing" in text or "पेमेंट" in text:
                intent = "distributor_existing"
            
            return f'{{"intent": "{intent}", "confidence": 0.9, "language": "hinglish"}}'

        if "agronomy assistant" in system.lower():
            # Check sessions to determine if pest or disease is being simulated
            confidence = 0.8
            problem = "pest_attack"
            for s in in_memory_db.tables["sessions"]:
                if s.get("current_step") == "F_PHOTO":
                    ph = s.get("whatsapp_phone")
                    col = s.get("collected_json") or {}
                    if ph == "919000000002" or "fungal_disease" in col.get("problem_category", []):
                        confidence = 0.5
                        problem = "fungal_disease"
                    elif ph == "919000000009":
                        confidence = 0.0
                        problem = "unclear"
                        
            return f'{{"problem_category": "{problem}", "secondary_possibilities": [], "severity": "medium", "confidence": {confidence}, "visible_symptoms_hindi": "पत्तियों पर लक्षण", "needs_human": false}}'

        # 3. Subject Summarizer Mocking
        if "customer support assistant" in system.lower() or "summarize" in system.lower():
            return "Payment stuck issue"

        return "Mock AI response"

mock_ai_provider = MockAIProvider()

# --- Inject Mocks into app modules BEFORE imports of tests ---
import app.db.client
app.db.client.supabase_client = mock_supabase_client

import app.whatsapp.client
app.whatsapp.client.whatsapp_client = mock_whatsapp_client

import app.ai.provider
app.ai.provider.ai_provider = mock_ai_provider

# Ensure existing repositories utilize the mock
import app.db.repositories.sessions
app.db.repositories.sessions.supabase_client = mock_supabase_client

import app.db.repositories.leads
app.db.repositories.leads.supabase_client = mock_supabase_client

import app.db.repositories.distributors
app.db.repositories.distributors.supabase_client = mock_supabase_client

import app.db.repositories.tickets
app.db.repositories.tickets.supabase_client = mock_supabase_client

import app.db.repositories.conversations
app.db.repositories.conversations.supabase_client = mock_supabase_client

import app.db.repositories.rules
app.db.repositories.rules.supabase_client = mock_supabase_client

import app.db.repositories.crops
app.db.repositories.crops.supabase_client = mock_supabase_client

import app.db.repositories.regions
app.db.repositories.regions.supabase_client = mock_supabase_client

import app.db.repositories.products
app.db.repositories.products.supabase_client = mock_supabase_client

import app.db.repositories.followups
app.db.repositories.followups.supabase_client = mock_supabase_client

import app.whatsapp.parser
app.whatsapp.parser.supabase_client = mock_supabase_client

import app.whatsapp.window
app.whatsapp.window.supabase_client = mock_supabase_client

import app.flows.farmer
app.flows.farmer.supabase_client = mock_supabase_client

import app.services.dealer_locator
app.services.dealer_locator.supabase_client = mock_supabase_client

import app.services.followup
app.services.followup.supabase_client = mock_supabase_client

import app.services.metrics
app.services.metrics.supabase_client = mock_supabase_client

import app.services.notify
app.services.notify.supabase_client = mock_supabase_client

import app.services.recommender
app.services.recommender.supabase_client = mock_supabase_client

import app.flows.distributor_new
app.flows.distributor_new.supabase_client = mock_supabase_client

import app.flows.distributor_existing
app.flows.distributor_existing.supabase_client = mock_supabase_client

import app.flows.router
app.flows.router.supabase_client = mock_supabase_client

# Override whatsapp_client in all flows and services
import app.flows.farmer
app.flows.farmer.whatsapp_client = mock_whatsapp_client

import app.flows.distributor_new
app.flows.distributor_new.whatsapp_client = mock_whatsapp_client

import app.flows.distributor_existing
app.flows.distributor_existing.whatsapp_client = mock_whatsapp_client

import app.flows.router
app.flows.router.whatsapp_client = mock_whatsapp_client

import app.services.recommender
app.services.recommender.whatsapp_client = mock_whatsapp_client

import app.services.notify
app.services.notify.whatsapp_client = mock_whatsapp_client

import app.whatsapp.window
app.whatsapp.window.whatsapp_client = mock_whatsapp_client

import app.api.webhook
app.api.webhook.whatsapp_client = mock_whatsapp_client

# Override ai_provider in all modules
import app.ai.intent
app.ai.intent.ai_provider = mock_ai_provider

import app.ai.vision
app.ai.vision.ai_provider = mock_ai_provider

import app.services.ticketing
app.services.ticketing.ai_provider = mock_ai_provider


@pytest.fixture(autouse=True)
def clean_db_and_wa():
    in_memory_db.clear_all()
    in_memory_db.seed_defaults()
    mock_whatsapp_client.clear()
    mock_ai_provider.should_fail = False
    
    # Reset circuit breaker
    from app.core.errors import ai_circuit_breaker
    ai_circuit_breaker.state = "CLOSED"
    ai_circuit_breaker.failure_count = 0
    
    yield
