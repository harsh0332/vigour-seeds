# Monitoring & Observability Guide

This document outlines key metrics, dashboards, alert channels, and incident response procedures for the Vigour Seeds WhatsApp platform.

## Key Metrics to Monitor

| Metric | Target / Threshold | Alert Condition | Description |
|---|---|---|---|
| **Webhook 200 Rate** | 100% | < 99% in 5m | All webhook requests must return HTTP 200 to Meta to prevent duplicate delivery retries. |
| **Meta Send Failure Rate** | < 2% | > 5% in 15m | Outbound messages failing to be delivered or rejected by Meta Graph API. |
| **AI Latency** | Avg < 2.0s | Avg > 5.0s in 5m | Total response time of the AI completion (intent routing, classification). |
| **AI Cost / Token Usage** | < $5.00 / day | > $15.00 / day | Daily API spending on Gemini / LLM calls. |
| **Escalation Rate** | < 10% | > 25% of sessions | Percentage of farmer leads forwarded to human agronomists due to low confidence or unclear issues. |
| **Follow-up Delivery** | > 95% | < 80% expected | Checks whether scheduled cron job follow-ups are successfully dispatched. |

---

## Observability Stack

### 1. Prometheus / `/metrics` Endpoint
The application exposes a standard metrics schema via the `/metrics` endpoint. The metrics service tracks:
* `msgs_in` (counter): Inbound WhatsApp messages received.
* `msgs_out` (counter): Outbound WhatsApp messages sent.
* `intents` (labels): Count of identified farmer/distributor intents.
* `farmer_qualified` (counter): Farmers who completed the qualification flow.
* `recos_sent` (counter): Recommendations dispatched to farmers.
* `escalations` (counter): Handed off to human agronomists.
* `distributors_scored` (counters by HOT/WARM/COLD): Leads scored and assigned a temperature.
* `tickets_open` (counter): Opened support tickets.
* `followups_sent` (counter): Cron follow-ups sent.
* `ai_errors` (counter): Circuit-breaker trip events or API failure rates.
* `avg_response_time_seconds` (gauge): Rolling average response duration.

### 2. Structured JSON Logging
All application logs are printed in standard JSON format containing context details (such as `lead_id`, `trace_id`, and `execution_time_seconds`).
> [!IMPORTANT]
> **Privacy Compliance**: All logs containing user identifiers MUST have the phone number redacted using `redact_phone()`.

---

## Alert Dispatching & Incident Response

### Circuit Breaker States
The AI API client is protected by a circuit breaker:
* **CLOSED**: Normal operations.
* **OPEN**: Triggered after **3 consecutive failures**. Gracefully degrades to:
  * Farmer: Escalates directly to human agronomist.
  * Router: Routes to human fallback.
  * Cooldown period is **30 seconds** before testing `HALF_OPEN`.

### Triggering Alerts
Unhandled exceptions automatically trigger system alerts:
* **Log Alert**: Logs a `CRITICAL` message in JSON format.
* **Slack / Webhook Alert**: If `ALERT_CHANNEL=webhook` and `ALERT_WEBHOOK_URL` is set, a Slack/Teams notification is sent immediately.

---

## Failure Triage Playbook

1. **Webhook 200 Rate drops below 100%**
   * *Check*: Render logs for any unhandled exceptions or syntax errors bypassing the global exception handler.
   * *Fix*: Ensure database connection limits in Supabase are not exhausted.

2. **AI Circuit Breaker Trips (OPEN)**
   * *Check*: Is the Gemini API key expired or has quota been exceeded?
   * *Fix*: Temporarily switch `AI_PROVIDER` to `openai` or `anthropic` in Render env variables, or wait for cooldown.
