from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import date, datetime

class CropRow(BaseModel):
    crop_id: str
    crop_category: Optional[str] = None
    crop_name_en: Optional[str] = None
    crop_name_hi: Optional[str] = None
    season: Optional[str] = None
    primary_states: Optional[str] = None
    whatsapp_button_label: Optional[str] = None
    in_catalog: str = "Y"

class ProductRow(BaseModel):
    product_id: str
    crop_category: Optional[str] = None
    crop: Optional[str] = None
    variety_name: Optional[str] = None
    duration_days: Optional[str] = None
    season: Optional[str] = None
    plant_height: Optional[str] = None
    key_traits: Optional[str] = None
    pest_disease_tolerance: Optional[str] = None
    fruit_grain_quality: Optional[str] = None
    yield_indicator: Optional[str] = None
    recommended_irrigation: Optional[str] = None
    target_problem_fit: Optional[str] = None
    target_region: Optional[str] = None
    mrp_inr: Optional[float] = None
    pack_size: Optional[str] = None
    distributor_availability: Optional[str] = None
    approved_for_recommendation: str = "Y"
    image_url: Optional[str] = None
    source_url: Optional[str] = None
    last_verified_date: Optional[date] = None

class DistributorActiveRow(BaseModel):
    distributor_id: str
    whatsapp_phone: str
    contact_name: str
    shop_name: str
    state: str
    district: str
    territory_code: str
    onboarded_date: date
    distributor_tier: Optional[str] = None
    credit_limit_inr: Optional[float] = None
    outstanding_balance_inr: Optional[float] = None
    assigned_sales_rep: str
    assigned_sales_rep_phone: str
    nearest_depot: Optional[str] = None
    last_order_date: Optional[date] = None
    active_status: str = "active"
    notes_internal: Optional[str] = None

class LeadFarmerRow(BaseModel):
    lead_id: str
    whatsapp_phone: str
    whatsapp_display_name: Optional[str] = None
    user_type: str = "farmer"
    lead_status: str = "new"
    lead_score: Optional[str] = None
    name: str
    state: str
    district: str
    village: Optional[str] = None
    preferred_language: Optional[str] = None
    total_land: Optional[float] = None
    land_unit: Optional[str] = None
    irrigation_source: Optional[List[str]] = None
    is_irrigated: Optional[bool] = None
    current_crop: Optional[str] = None
    previous_crop: Optional[str] = None
    crop_stage: Optional[str] = None
    sowing_date: Optional[date] = None
    variety_used: Optional[str] = None
    variety_brand: Optional[str] = None
    help_needed_for: str
    expected_yield_qtl_per_acre: Optional[float] = None
    actual_yield_last_year: Optional[float] = None
    problem_category: Optional[List[str]] = None
    problem_description_user: Optional[str] = None
    problem_severity_ai: Optional[str] = None
    photo_url: Optional[str] = None
    photo_ai_diagnosis: Optional[str] = None
    photo_ai_confidence: Optional[float] = None
    recommended_product_ids: Optional[List[str]] = None
    recommendation_sent_at: Optional[datetime] = None
    next_action: Optional[str] = None
    nearest_dealer_id: Optional[str] = None
    last_message_at: datetime
    next_followup_at: Optional[datetime] = None
    followup_count: int = 0
    escalated_to_human: bool = False
    assigned_agronomist: Optional[str] = None
    source_channel: str
    utm_campaign: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    notes_internal: Optional[str] = None

class LeadDistributorNewRow(BaseModel):
    lead_id: str
    whatsapp_phone: str
    contact_name: str
    shop_name: str
    state: str
    district: str
    city_town: Optional[str] = None
    pincode: Optional[str] = None
    current_brands_sold: Optional[List[str]] = None
    monthly_sales_volume_inr: float
    area_covered_radius_km: Optional[float] = None
    shop_size_sqft: Optional[float] = None
    warehouse_available: Optional[bool] = None
    warehouse_size_sqft: Optional[float] = None
    staff_size: Optional[int] = None
    years_in_agri_business: Optional[float] = None
    interested_segments: List[str]
    interested_crops: Optional[List[str]] = None
    lead_score: Optional[str] = None
    lead_status: str = "new"
    assigned_sales_rep: Optional[str] = None
    callback_requested: Optional[bool] = None
    callback_time_preference: Optional[str] = None
    source_channel: str
    created_at: datetime
    updated_at: datetime
    notes_internal: Optional[str] = None

class ConversationRow(BaseModel):
    message_id: str
    lead_id: str
    whatsapp_phone: str
    direction: str
    message_type: str
    message_text: Optional[str] = None
    media_url: Optional[str] = None
    button_payload: Optional[str] = None
    ai_intent_detected: Optional[str] = None
    ai_confidence: Optional[float] = None
    handled_by: str
    handoff_triggered: bool = False
    response_time_seconds: Optional[float] = None
    template_id: Optional[str] = None
    language: Optional[str] = None
    created_at: datetime

class TicketRow(BaseModel):
    ticket_id: str
    lead_id: str
    whatsapp_phone: str
    user_type: str
    ticket_category: str
    ticket_priority: str
    ticket_status: str = "open"
    subject: str
    description: str
    assigned_team: str
    assigned_person: Optional[str] = None
    related_order_id: Optional[str] = None
    related_product_id: Optional[str] = None
    sla_target_hours: float
    first_response_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    user_satisfaction_score: Optional[int] = None
    created_at: datetime
    updated_at: datetime

class FollowupRow(BaseModel):
    id: Optional[int] = None
    user_type: str
    lead_status: str
    day: int
    send_after_hours: int
    message_template_id: str
    message_text_hindi: str
    next_action_if_no_reply: str

class RecommendationRuleRow(BaseModel):
    rule_id: str
    crop: str
    crop_stage: str
    problem_category: str
    irrigation_type: str
    region: str
    recommended_product_ids: Optional[str] = None
    next_action: str
    human_review_required: bool
    notes: Optional[str] = None

class RegionRow(BaseModel):
    region_id: str
    state: str
    state_code: str
    priority_districts: Optional[str] = None
    nearest_depot: Optional[str] = None
    depot_address: Optional[str] = None
    sales_rep_name: Optional[str] = None
    sales_rep_phone: Optional[str] = None
    agronomist_name: Optional[str] = None
    agronomist_phone: Optional[str] = None
    is_active: str = "Y"

class SessionRow(BaseModel):
    whatsapp_phone: str
    user_type: Optional[str] = None
    current_flow: Optional[str] = None
    current_step: str
    collected_json: Dict[str, Any] = Field(default_factory=dict)
    preferred_language: Optional[str] = None
    last_message_at: datetime
    updated_at: datetime
