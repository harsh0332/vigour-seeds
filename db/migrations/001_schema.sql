-- DDL Schema for Vigour Seeds WhatsApp Agent (Phase 2)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Crops Master
CREATE TABLE IF NOT EXISTS crops (
    crop_id VARCHAR(50) PRIMARY KEY,
    crop_category VARCHAR(100),
    crop_name_en VARCHAR(100),
    crop_name_hi VARCHAR(100),
    season VARCHAR(100),
    primary_states TEXT,
    whatsapp_button_label VARCHAR(100),
    in_catalog VARCHAR(10) NOT NULL DEFAULT 'Y'
);

-- 2. Products Master
CREATE TABLE IF NOT EXISTS products (
    product_id VARCHAR(50) PRIMARY KEY,
    crop_category VARCHAR(100),
    crop VARCHAR(100),
    variety_name VARCHAR(100),
    duration_days VARCHAR(100),
    season VARCHAR(100),
    plant_height VARCHAR(100),
    key_traits TEXT,
    pest_disease_tolerance TEXT,
    fruit_grain_quality TEXT,
    yield_indicator VARCHAR(100),
    recommended_irrigation VARCHAR(100),
    target_problem_fit TEXT,
    target_region TEXT,
    mrp_inr NUMERIC(10, 2),
    pack_size VARCHAR(100),
    distributor_availability TEXT,
    approved_for_recommendation VARCHAR(10) NOT NULL DEFAULT 'Y',
    image_url TEXT,
    source_url TEXT,
    last_verified_date DATE
);

CREATE INDEX IF NOT EXISTS idx_products_crop_cat ON products(crop, crop_category);

-- 3. Distributors Active (Existing Distributor Schema)
CREATE TABLE IF NOT EXISTS distributors_active (
    distributor_id VARCHAR(100) PRIMARY KEY,
    whatsapp_phone VARCHAR(50) NOT NULL UNIQUE,
    contact_name VARCHAR(255) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    state VARCHAR(100) NOT NULL,
    district VARCHAR(100) NOT NULL,
    territory_code VARCHAR(50) NOT NULL,
    onboarded_date DATE NOT NULL,
    distributor_tier VARCHAR(50),
    credit_limit_inr NUMERIC(15, 2),
    outstanding_balance_inr NUMERIC(15, 2),
    assigned_sales_rep VARCHAR(255) NOT NULL,
    assigned_sales_rep_phone VARCHAR(50) NOT NULL,
    nearest_depot VARCHAR(255),
    last_order_date DATE,
    active_status VARCHAR(50) NOT NULL DEFAULT 'active',
    notes_internal TEXT
);

CREATE INDEX IF NOT EXISTS idx_distributors_phone ON distributors_active(whatsapp_phone);

-- 4. Leads Farmer (Lead Farmer Schema)
CREATE TABLE IF NOT EXISTS leads_farmer (
    lead_id VARCHAR(100) PRIMARY KEY,
    whatsapp_phone VARCHAR(50) NOT NULL UNIQUE,
    whatsapp_display_name VARCHAR(255),
    user_type VARCHAR(50) NOT NULL DEFAULT 'farmer',
    lead_status VARCHAR(50) NOT NULL DEFAULT 'new',
    lead_score VARCHAR(50),
    name VARCHAR(255) NOT NULL,
    state VARCHAR(100) NOT NULL,
    district VARCHAR(100) NOT NULL,
    village VARCHAR(255),
    preferred_language VARCHAR(50),
    total_land NUMERIC(10, 2),
    land_unit VARCHAR(50),
    irrigation_source TEXT[],
    is_irrigated BOOLEAN,
    current_crop VARCHAR(50) REFERENCES crops(crop_id),
    previous_crop VARCHAR(50) REFERENCES crops(crop_id),
    crop_stage VARCHAR(50),
    sowing_date DATE,
    variety_used TEXT,
    variety_brand VARCHAR(50),
    help_needed_for VARCHAR(50) NOT NULL,
    expected_yield_qtl_per_acre NUMERIC(10, 2),
    actual_yield_last_year NUMERIC(10, 2),
    problem_category TEXT[],
    problem_description_user TEXT,
    problem_severity_ai VARCHAR(50),
    photo_url TEXT,
    photo_ai_diagnosis TEXT,
    photo_ai_confidence NUMERIC(3, 2),
    recommended_product_ids TEXT[],
    recommendation_sent_at TIMESTAMPTZ,
    next_action VARCHAR(50),
    nearest_dealer_id VARCHAR(100) REFERENCES distributors_active(distributor_id),
    last_message_at TIMESTAMPTZ NOT NULL,
    next_followup_at TIMESTAMPTZ,
    followup_count INT DEFAULT 0,
    escalated_to_human BOOLEAN DEFAULT FALSE,
    assigned_agronomist VARCHAR(255),
    source_channel VARCHAR(50) NOT NULL,
    utm_campaign TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes_internal TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_farmer_phone ON leads_farmer(whatsapp_phone);

-- 5. Leads Distributor New (Lead Distributor Schema)
CREATE TABLE IF NOT EXISTS leads_distributor_new (
    lead_id VARCHAR(100) PRIMARY KEY,
    whatsapp_phone VARCHAR(50) NOT NULL UNIQUE,
    contact_name VARCHAR(255) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    state VARCHAR(100) NOT NULL,
    district VARCHAR(100) NOT NULL,
    city_town VARCHAR(255),
    pincode VARCHAR(20),
    current_brands_sold TEXT[],
    monthly_sales_volume_inr NUMERIC(15, 2) NOT NULL,
    area_covered_radius_km NUMERIC(10, 2),
    shop_size_sqft NUMERIC(10, 2),
    warehouse_available BOOLEAN,
    warehouse_size_sqft NUMERIC(10, 2),
    staff_size INT,
    years_in_agri_business NUMERIC(5, 2),
    interested_segments TEXT[] NOT NULL,
    interested_crops VARCHAR(50)[],
    lead_score VARCHAR(50),
    lead_status VARCHAR(50) NOT NULL DEFAULT 'new',
    assigned_sales_rep VARCHAR(255),
    callback_requested BOOLEAN,
    callback_time_preference VARCHAR(255),
    source_channel VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes_internal TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_dist_new_phone ON leads_distributor_new(whatsapp_phone);

-- 6. Conversations (Conversation Log Schema)
CREATE TABLE IF NOT EXISTS conversations (
    message_id VARCHAR(255) PRIMARY KEY,
    lead_id VARCHAR(100) NOT NULL,
    whatsapp_phone VARCHAR(50) NOT NULL,
    direction VARCHAR(50) NOT NULL,
    message_type VARCHAR(50) NOT NULL,
    message_text TEXT,
    media_url TEXT,
    button_payload TEXT,
    ai_intent_detected VARCHAR(50),
    ai_confidence NUMERIC(3, 2),
    handled_by VARCHAR(50) NOT NULL,
    handoff_triggered BOOLEAN DEFAULT FALSE,
    response_time_seconds NUMERIC(10, 2),
    template_id VARCHAR(100),
    language VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conv_phone ON conversations(whatsapp_phone);
CREATE INDEX IF NOT EXISTS idx_conv_lead_id ON conversations(lead_id);
CREATE INDEX IF NOT EXISTS idx_conv_created ON conversations(created_at);

-- 7. Tickets (Ticket Schema)
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id VARCHAR(100) PRIMARY KEY,
    lead_id VARCHAR(100) NOT NULL,
    whatsapp_phone VARCHAR(50) NOT NULL,
    user_type VARCHAR(50) NOT NULL,
    ticket_category VARCHAR(100) NOT NULL,
    ticket_priority VARCHAR(50) NOT NULL,
    ticket_status VARCHAR(50) NOT NULL DEFAULT 'open',
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    assigned_team VARCHAR(50) NOT NULL,
    assigned_person VARCHAR(255),
    related_order_id VARCHAR(100),
    related_product_id VARCHAR(50) REFERENCES products(product_id),
    sla_target_hours NUMERIC(5, 2) NOT NULL,
    first_response_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,
    user_satisfaction_score INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 8. Followups (Followup Schema)
CREATE TABLE IF NOT EXISTS followups (
    id SERIAL PRIMARY KEY,
    user_type VARCHAR(50) NOT NULL,
    lead_status VARCHAR(50) NOT NULL,
    day INT NOT NULL,
    send_after_hours INT NOT NULL,
    message_template_id VARCHAR(100) NOT NULL,
    message_text_hindi TEXT NOT NULL,
    next_action_if_no_reply VARCHAR(100) NOT NULL
);

-- 9. Recommendation Rules (Recommendation Logic)
CREATE TABLE IF NOT EXISTS recommendation_rules (
    rule_id VARCHAR(50) PRIMARY KEY,
    crop VARCHAR(100) NOT NULL,
    crop_stage VARCHAR(100) NOT NULL,
    problem_category VARCHAR(100) NOT NULL,
    irrigation_type VARCHAR(100) NOT NULL,
    region VARCHAR(255) NOT NULL,
    recommended_product_ids TEXT,
    next_action VARCHAR(100) NOT NULL,
    human_review_required BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT
);

-- 10. Regions (Region Master)
CREATE TABLE IF NOT EXISTS regions (
    region_id VARCHAR(50) PRIMARY KEY,
    state VARCHAR(100) NOT NULL,
    state_code VARCHAR(10) NOT NULL,
    priority_districts TEXT,
    nearest_depot VARCHAR(255),
    depot_address TEXT,
    sales_rep_name VARCHAR(255),
    sales_rep_phone VARCHAR(50),
    agronomist_name VARCHAR(255),
    agronomist_phone VARCHAR(50),
    is_active VARCHAR(10) NOT NULL DEFAULT 'Y'
);

CREATE INDEX IF NOT EXISTS idx_regions_state_code ON regions(state_code);

-- 11. Sessions (Application Session State)
CREATE TABLE IF NOT EXISTS sessions (
    whatsapp_phone VARCHAR(50) PRIMARY KEY,
    user_type VARCHAR(50),
    current_flow VARCHAR(100),
    current_step VARCHAR(100) NOT NULL,
    collected_json JSONB DEFAULT '{}'::jsonb,
    preferred_language VARCHAR(50),
    last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Triggers for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE OR REPLACE TRIGGER update_leads_farmer_updated_at
    BEFORE UPDATE ON leads_farmer
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE TRIGGER update_leads_distributor_new_updated_at
    BEFORE UPDATE ON leads_distributor_new
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE TRIGGER update_tickets_updated_at
    BEFORE UPDATE ON tickets
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE TRIGGER update_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
