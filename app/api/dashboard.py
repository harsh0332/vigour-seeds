import os
import asyncio
from datetime import datetime
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

from app.db.client import supabase_client
from app.services.metrics import metrics_service
from app.core.logging import logger

router = APIRouter()
security = HTTPBasic()

def authenticate_dashboard_user(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.environ.get("DASHBOARD_USER", "admin")
    correct_password = os.environ.get("DASHBOARD_PASS", "vigour123")
    
    is_correct_username = secrets.compare_digest(credentials.username, correct_username)
    is_correct_password = secrets.compare_digest(credentials.password, correct_password)
    
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(username: str = Depends(authenticate_dashboard_user)):
    # 1. Gather Metrics from in-memory metrics service
    metrics = metrics_service.get_metrics_dict()
    
    # 2. Query Database for details (gracefully fall back on exceptions)
    distributor_leads = []
    open_tickets = []
    active_escalations = []
    
    db_metrics = {
        "total_farmers": 0,
        "total_distributors": 0,
        "open_tickets_count": 0,
        "active_escalations_count": 0
    }
    
    if supabase_client:
        try:
            # Fetch recent distributor leads
            res_dist = await asyncio.to_thread(
                lambda: supabase_client.table("leads_distributor_new")
                .select("*")
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            distributor_leads = res_dist.data or []
            
            # Fetch open tickets
            res_tkt = await asyncio.to_thread(
                lambda: supabase_client.table("tickets")
                .select("*")
                .eq("ticket_status", "open")
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            open_tickets = res_tkt.data or []
            
            # Fetch active escalations (farmers escalated to human)
            res_esc = await asyncio.to_thread(
                lambda: supabase_client.table("leads_farmer")
                .select("*")
                .eq("escalated_to_human", True)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            active_escalations = res_esc.data or []
            
            # Count metrics
            db_metrics["open_tickets_count"] = len(open_tickets)
            db_metrics["active_escalations_count"] = len(active_escalations)
            
            res_farmer_count = await asyncio.to_thread(
                lambda: supabase_client.table("leads_farmer").select("lead_id", count="exact").execute()
            )
            db_metrics["total_farmers"] = res_farmer_count.count or len(res_farmer_count.data or [])
            
            res_dist_count = await asyncio.to_thread(
                lambda: supabase_client.table("leads_distributor_new").select("lead_id", count="exact").execute()
            )
            db_metrics["total_distributors"] = res_dist_count.count or len(res_dist_count.data or [])
            
        except Exception as e:
            logger.error("Failed to fetch dashboard data from Supabase", extra={"error": str(e)})
            
    # Classify distributor leads into bands
    categorized_distributors = {"HOT": [], "WARM": [], "COLD": []}
    for lead in distributor_leads:
        score_val = 0.0
        score_raw = lead.get("lead_score")
        if score_raw is not None:
            try:
                score_val = float(score_raw)
            except (ValueError, TypeError):
                pass
        
        band = "COLD"
        if score_val >= 70.0:
            band = "HOT"
        elif score_val >= 45.0:
            band = "WARM"
            
        lead_with_band = dict(lead)
        lead_with_band["band"] = band
        lead_with_band["parsed_score"] = score_val
        categorized_distributors[band].append(lead_with_band)

    # HTML response with sleek Outfit/Inter dark-mode glassmorphic styling
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Vigour Seeds - Ops Dashboard</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg-primary: #0a0e17;
                --bg-card: rgba(18, 26, 44, 0.6);
                --border-color: rgba(255, 255, 255, 0.08);
                --text-primary: #f3f4f6;
                --text-secondary: #9ca3af;
                --primary: #8b5cf6;
                --primary-glow: rgba(139, 92, 246, 0.15);
                --success: #10b981;
                --success-glow: rgba(16, 185, 129, 0.15);
                --warning: #f59e0b;
                --warning-glow: rgba(245, 158, 11, 0.15);
                --danger: #ef4444;
                --danger-glow: rgba(239, 68, 68, 0.15);
                --info: #06b6d4;
                --info-glow: rgba(6, 182, 212, 0.15);
            }}

            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}

            body {{
                font-family: 'Inter', sans-serif;
                background-color: var(--bg-primary);
                color: var(--text-primary);
                padding: 2rem;
                min-height: 100vh;
                background-image: 
                    radial-gradient(at 10% 20%, rgba(139, 92, 246, 0.15) 0px, transparent 50%),
                    radial-gradient(at 90% 80%, rgba(6, 182, 212, 0.15) 0px, transparent 50%);
                background-attachment: fixed;
            }}

            h1, h2, h3 {{
                font-family: 'Outfit', sans-serif;
                font-weight: 600;
            }}

            /* Header Section */
            header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 2.5rem;
                padding-bottom: 1.5rem;
                border-bottom: 1px solid var(--border-color);
            }}

            .logo-section {{
                display: flex;
                align-items: center;
                gap: 0.75rem;
            }}

            .logo-icon {{
                width: 40px;
                height: 40px;
                background: linear-gradient(135deg, var(--primary), var(--info));
                border-radius: 12px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: 800;
                font-family: 'Outfit', sans-serif;
                font-size: 1.25rem;
                color: #fff;
                box-shadow: 0 4px 20px rgba(139, 92, 246, 0.3);
            }}

            .logo-title {{
                font-size: 1.75rem;
                background: linear-gradient(to right, #fff, #a78bfa);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }}

            .status-badge {{
                display: flex;
                align-items: center;
                gap: 0.5rem;
                background: rgba(16, 185, 129, 0.1);
                border: 1px solid rgba(16, 185, 129, 0.2);
                padding: 0.5rem 1rem;
                border-radius: 9999px;
                color: var(--success);
                font-size: 0.875rem;
                font-weight: 500;
            }}

            .status-dot {{
                width: 8px;
                height: 8px;
                background-color: var(--success);
                border-radius: 50%;
                animation: pulse 2s infinite;
            }}

            @keyframes pulse {{
                0% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }}
                70% {{ transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }}
                100% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }}
            }}

            /* Dashboard Grid */
            .metrics-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 1.5rem;
                margin-bottom: 2.5rem;
            }}

            .metric-card {{
                background: var(--bg-card);
                backdrop-filter: blur(12px);
                -webkit-backdrop-filter: blur(12px);
                border: 1px solid var(--border-color);
                border-radius: 16px;
                padding: 1.5rem;
                position: relative;
                overflow: hidden;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }}

            .metric-card:hover {{
                transform: translateY(-4px);
                border-color: rgba(255, 255, 255, 0.15);
                box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
            }}

            .metric-card::before {{
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 4px;
                height: 100%;
            }}

            .metric-card.purple::before {{ background: var(--primary); }}
            .metric-card.green::before {{ background: var(--success); }}
            .metric-card.orange::before {{ background: var(--warning); }}
            .metric-card.red::before {{ background: var(--danger); }}
            .metric-card.blue::before {{ background: var(--info); }}

            .metric-label {{
                font-size: 0.875rem;
                color: var(--text-secondary);
                text-transform: uppercase;
                letter-spacing: 0.05em;
                margin-bottom: 0.5rem;
            }}

            .metric-value {{
                font-size: 2.25rem;
                font-weight: 700;
                font-family: 'Outfit', sans-serif;
                line-height: 1;
            }}

            .metric-subtext {{
                font-size: 0.75rem;
                color: var(--text-secondary);
                margin-top: 0.5rem;
            }}

            /* Two Column Content Layout */
            .content-grid {{
                display: grid;
                grid-template-columns: 1.2fr 1fr;
                gap: 2rem;
            }}

            @media (max-width: 1024px) {{
                .content-grid {{
                    grid-template-columns: 1fr;
                }}
            }}

            .panel {{
                background: var(--bg-card);
                backdrop-filter: blur(12px);
                -webkit-backdrop-filter: blur(12px);
                border: 1px solid var(--border-color);
                border-radius: 20px;
                padding: 2rem;
                display: flex;
                flex-direction: column;
                gap: 1.5rem;
            }}

            .panel-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid var(--border-color);
                padding-bottom: 1rem;
            }}

            .panel-title {{
                font-size: 1.25rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }}

            /* Tabs styling */
            .tabs {{
                display: flex;
                gap: 0.5rem;
                background: rgba(0, 0, 0, 0.2);
                padding: 0.25rem;
                border-radius: 8px;
                border: 1px solid var(--border-color);
            }}

            .tab-btn {{
                background: transparent;
                border: none;
                color: var(--text-secondary);
                padding: 0.4rem 0.8rem;
                border-radius: 6px;
                cursor: pointer;
                font-size: 0.8125rem;
                font-weight: 500;
                transition: all 0.2s;
            }}

            .tab-btn.active {{
                background: var(--primary);
                color: #fff;
            }}

            /* Table/List styling */
            .scroll-list {{
                max-height: 480px;
                overflow-y: auto;
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                padding-right: 0.5rem;
            }}

            .scroll-list::-webkit-scrollbar {{
                width: 6px;
            }}
            .scroll-list::-webkit-scrollbar-track {{
                background: transparent;
            }}
            .scroll-list::-webkit-scrollbar-thumb {{
                background: rgba(255, 255, 255, 0.1);
                border-radius: 3px;
            }}
            .scroll-list::-webkit-scrollbar-thumb:hover {{
                background: rgba(255, 255, 255, 0.2);
            }}

            .lead-item {{
                background: rgba(255, 255, 255, 0.02);
                border: 1px solid var(--border-color);
                border-radius: 12px;
                padding: 1rem;
                display: flex;
                justify-content: space-between;
                align-items: center;
                transition: all 0.2s;
            }}

            .lead-item:hover {{
                background: rgba(255, 255, 255, 0.04);
                border-color: rgba(255, 255, 255, 0.12);
            }}

            .lead-info {{
                display: flex;
                flex-direction: column;
                gap: 0.25rem;
            }}

            .lead-name {{
                font-weight: 600;
                font-size: 0.95rem;
            }}

            .lead-meta {{
                font-size: 0.75rem;
                color: var(--text-secondary);
                display: flex;
                gap: 0.75rem;
            }}

            .badge {{
                font-size: 0.6875rem;
                font-weight: 700;
                padding: 0.25rem 0.5rem;
                border-radius: 4px;
                text-transform: uppercase;
            }}

            .badge.hot {{ background: var(--danger-glow); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.2); }}
            .badge.warm {{ background: var(--warning-glow); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.2); }}
            .badge.cold {{ background: var(--info-glow); color: var(--info); border: 1px solid rgba(6, 182, 212, 0.2); }}
            
            .badge.priority-high {{ background: var(--danger-glow); color: var(--danger); }}
            .badge.priority-medium {{ background: var(--warning-glow); color: var(--warning); }}
            .badge.priority-low {{ background: var(--success-glow); color: var(--success); }}

            .badge.status-open {{ background: var(--primary-glow); color: var(--primary); }}

            .action-btn {{
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid var(--border-color);
                color: var(--text-primary);
                padding: 0.4rem 0.8rem;
                border-radius: 8px;
                font-size: 0.8125rem;
                cursor: pointer;
                transition: all 0.2s;
            }}

            .action-btn:hover {{
                background: rgba(255, 255, 255, 0.1);
                border-color: rgba(255, 255, 255, 0.2);
            }}

            .ticket-item {{
                background: rgba(255, 255, 255, 0.02);
                border: 1px solid var(--border-color);
                border-radius: 12px;
                padding: 1rem;
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }}

            .ticket-title-row {{
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
            }}

            .ticket-subject {{
                font-weight: 600;
                font-size: 0.95rem;
            }}

            .ticket-desc {{
                font-size: 0.8125rem;
                color: var(--text-secondary);
                line-height: 1.4;
            }}

            .ticket-footer {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-size: 0.75rem;
                color: var(--text-secondary);
                margin-top: 0.25rem;
                border-top: 1px dashed var(--border-color);
                padding-top: 0.5rem;
            }}

            .empty-state {{
                text-align: center;
                padding: 2.5rem 1rem;
                color: var(--text-secondary);
                font-size: 0.875rem;
            }}

            .refresh-section {{
                display: flex;
                align-items: center;
                gap: 0.5rem;
                color: var(--text-secondary);
                font-size: 0.75rem;
            }}
            
            .refresh-btn {{
                background: none;
                border: none;
                color: var(--primary);
                cursor: pointer;
                font-weight: 600;
                text-decoration: underline;
            }}
        </style>
        <script>
            function filterDistributors(band) {{
                const items = document.querySelectorAll('.distributor-lead-item');
                const buttons = document.querySelectorAll('.tab-btn');
                
                buttons.forEach(btn => {{
                    if (btn.getAttribute('data-band') === band) {{
                        btn.classList.add('active');
                    }} else {{
                        btn.classList.remove('active');
                    }}
                }});

                items.forEach(item => {{
                    if (band === 'ALL' || item.getAttribute('data-band') === band) {{
                        item.style.display = 'flex';
                    }} else {{
                        item.style.display = 'none';
                    }}
                }});
            }}
        </script>
    </head>
    <body>
        <header>
            <div class="logo-section">
                <div class="logo-icon">V</div>
                <h1 class="logo-title">Vigour Seeds Ops</h1>
            </div>
            <div style="display: flex; align-items: center; gap: 1.5rem;">
                <div class="refresh-section">
                    Last refreshed: {datetime.utcnow().strftime("%H:%M:%S UTC")} | 
                    <button class="refresh-btn" onclick="window.location.reload()">Refresh Now</button>
                </div>
                <div class="status-badge">
                    <span class="status-dot"></span>
                    <span>Live Monitoring</span>
                </div>
            </div>
        </header>

        <!-- Metric Grid -->
        <div class="metrics-grid">
            <div class="metric-card purple">
                <div class="metric-label">Messages In</div>
                <div class="metric-value">{metrics.get("msgs_in", 0)}</div>
                <div class="metric-subtext">Total inbound user messages</div>
            </div>
            <div class="metric-card blue">
                <div class="metric-label">Messages Out</div>
                <div class="metric-value">{metrics.get("msgs_out", 0)}</div>
                <div class="metric-subtext">Total outbound replies</div>
            </div>
            <div class="metric-card green">
                <div class="metric-label">Qualified Leads</div>
                <div class="metric-value">{db_metrics["total_farmers"] + db_metrics["total_distributors"]}</div>
                <div class="metric-subtext">Farmers: {db_metrics["total_farmers"]} | Dealers: {db_metrics["total_distributors"]}</div>
            </div>
            <div class="metric-card orange">
                <div class="metric-label">Open Tickets</div>
                <div class="metric-value">{db_metrics["open_tickets_count"]}</div>
                <div class="metric-subtext">Requires team attention</div>
            </div>
            <div class="metric-card red">
                <div class="metric-label">Active Escalations</div>
                <div class="metric-value">{db_metrics["active_escalations_count"]}</div>
                <div class="metric-subtext">Agronomist review requested</div>
            </div>
        </div>

        <!-- Content Columns -->
        <div class="content-grid">
            <!-- Column 1: Distributor Leads categorized by Band -->
            <div class="panel">
                <div class="panel-header">
                    <h2 class="panel-title">Recent Distributor Leads</h2>
                    <div class="tabs">
                        <button class="tab-btn active" data-band="ALL" onclick="filterDistributors('ALL')">All ({len(distributor_leads)})</button>
                        <button class="tab-btn" data-band="HOT" onclick="filterDistributors('HOT')">Hot ({len(categorized_distributors["HOT"])})</button>
                        <button class="tab-btn" data-band="WARM" onclick="filterDistributors('WARM')">Warm ({len(categorized_distributors["WARM"])})</button>
                        <button class="tab-btn" data-band="COLD" onclick="filterDistributors('COLD')">Cold ({len(categorized_distributors["COLD"])})</button>
                    </div>
                </div>

                <div class="scroll-list">
                    {"" if distributor_leads else '<div class="empty-state">No distributor leads found in the system.</div>'}
                    """
    
    for lead in distributor_leads:
        band = lead.get("band", "COLD")
        score = lead.get("parsed_score", 0.0)
        phone = lead.get("whatsapp_phone", "")
        formatted_phone = f"+{phone[:2]} {phone[2:7]}-{phone[7:]}" if len(phone) >= 10 else phone
        created_at_dt = lead.get("created_at")
        formatted_date = ""
        if created_at_dt:
            try:
                formatted_date = datetime.fromisoformat(created_at_dt.replace("Z", "")).strftime("%b %d, %H:%M")
            except Exception:
                formatted_date = str(created_at_dt)

        html_content += f"""
                    <div class="lead-item distributor-lead-item" data-band="{band}">
                        <div class="lead-info">
                            <div class="lead-name">{lead.get("contact_name", "Unknown Contact")}</div>
                            <div style="font-size: 0.875rem; color: var(--text-secondary); font-weight: 500;">
                                {lead.get("shop_name", "Unknown Firm")}
                            </div>
                            <div class="lead-meta">
                                <span>📞 {formatted_phone}</span>
                                <span>📍 {lead.get("city_town", "") or lead.get("district", "")}, {lead.get("state", "")}</span>
                                <span>📅 {formatted_date}</span>
                            </div>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 0.5rem;">
                            <span class="badge {band.lower()}">{band}</span>
                            <span style="font-size: 0.75rem; color: var(--text-secondary); font-weight: 600;">Score: {score:.0f}</span>
                        </div>
                    </div>
        """

    html_content += """
                </div>
            </div>

            <!-- Column 2: Open Tickets & Active Escalations -->
            <div style="display: flex; flex-direction: column; gap: 2rem;">
                <!-- Open Tickets Panel -->
                <div class="panel">
                    <div class="panel-header">
                        <h2 class="panel-title">Open Tickets Queue ({len(open_tickets)})</h2>
                    </div>
                    <div class="scroll-list" style="max-height: 220px;">
                        {"" if open_tickets else '<div class="empty-state">No open tickets at this time.</div>'}
    """

    for t in open_tickets:
        phone = t.get("whatsapp_phone", "")
        priority = t.get("ticket_priority", "medium").lower()
        created_at_dt = t.get("created_at")
        formatted_date = ""
        if created_at_dt:
            try:
                formatted_date = datetime.fromisoformat(created_at_dt.replace("Z", "")).strftime("%b %d, %H:%M")
            except Exception:
                formatted_date = str(created_at_dt)

        html_content += f"""
                        <div class="ticket-item">
                            <div class="ticket-title-row">
                                <div class="ticket-subject">{t.get("subject", "No Subject")}</div>
                                <span class="badge priority-{priority}">{priority}</span>
                            </div>
                            <div class="ticket-desc">{t.get("description", "")}</div>
                            <div class="ticket-footer">
                                <span>ID: {t.get("ticket_id")} | Category: {t.get("ticket_category")}</span>
                                <span>📅 {formatted_date}</span>
                            </div>
                        </div>
        """

    html_content += """
                    </div>
                </div>

                <!-- Active Escalations Panel -->
                <div class="panel">
                    <div class="panel-header">
                        <h2 class="panel-title" style="color: var(--danger)">Active Escalations ({len(active_escalations)})</h2>
                    </div>
                    <div class="scroll-list" style="max-height: 220px;">
                        {"" if active_escalations else '<div class="empty-state">No active escalated cases.</div>'}
    """

    for esc in active_escalations:
        phone = esc.get("whatsapp_phone", "")
        formatted_phone = f"+{phone[:2]} {phone[2:7]}-{phone[7:]}" if len(phone) >= 10 else phone
        created_at_dt = esc.get("created_at")
        formatted_date = ""
        if created_at_dt:
            try:
                formatted_date = datetime.fromisoformat(created_at_dt.replace("Z", "")).strftime("%b %d, %H:%M")
            except Exception:
                formatted_date = str(created_at_dt)

        html_content += f"""
                        <div class="ticket-item" style="border-left: 3px solid var(--danger);">
                            <div class="ticket-title-row">
                                <div class="ticket-subject">{esc.get("name", "Farmer")} ({esc.get("current_crop", "Crop N/A")})</div>
                                <span class="badge priority-high">Escalated</span>
                            </div>
                            <div class="ticket-desc">
                                <b>Issue:</b> {esc.get("help_needed_for", "")}<br>
                                <b>AI diagnosis:</b> {esc.get("photo_ai_diagnosis", "None") or "None"}<br>
                                {f'🖼️ <a href="{esc.get("photo_url")}" target="_blank" style="color: var(--info); text-decoration: underline;">View Uploaded Photo</a>' if esc.get("photo_url") else ''}
                            </div>
                            <div class="ticket-footer">
                                <span>📞 {formatted_phone} | Location: {esc.get("district", "")}, {esc.get("state", "")}</span>
                                <span>📅 {formatted_date}</span>
                            </div>
                        </div>
        """

    html_content += """
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content, status_code=200)
