import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient, Response
from mongomock_motor import AsyncMongoMockClient

from app.config import settings
from app.database.mongodb import mongodb
from app.main import app
from app.schemas.user import UserRegister, normalize_phone_number
from app.security.password import hash_password
from app.services.alert_service import (
    evaluate_and_create_alert_from_edge,
    evaluate_and_create_alert_from_pipeline_result,
)
from app.services.notification_service import (
    mask_phone_number,
    textbee_sms_provider,
    twilio_sms_provider,
)


@pytest.fixture(autouse=True)
async def setup_test_db():
    """Setup isolated in-memory mongo mock for every test."""
    mock_client = AsyncMongoMockClient()
    mongodb.client = mock_client
    mongodb.db = mock_client["test_hvac_leak_detection"]
    mongodb.is_mock = True
    yield mongodb.db
    mock_client.close()


# ---------------------------------------------------------------------------
# Test 1 & 2: Registration accepts valid phone and persists to MongoDB
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_registration_accepts_valid_phone_number_and_persists(setup_test_db):
    db = setup_test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "email": "fieldtech@example.com",
            "password": "SecurePassword123",
            "full_name": "Field Technician John",
            "phone_number": "+1 (415) 555-0199",  # With formatting
            "role": "TECHNICIAN",
        }
        res = await client.post("/api/v1/auth/register", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["success"] is True
        assert "user_id" in data

    # Verify document in MongoDB
    saved_user = await db.users.find_one({"email": "fieldtech@example.com"})
    assert saved_user is not None
    assert saved_user["full_name"] == "Field Technician John"
    # Normalization should strip parentheses, spaces, dashes
    assert saved_user["phone_number"] == "+14155550199"
    assert saved_user["phone_verified"] is False
    assert saved_user["role"] == "TECHNICIAN"


# ---------------------------------------------------------------------------
# Test 3: Invalid phone numbers are rejected
# ---------------------------------------------------------------------------
@pytest.mark.anyio
@pytest.mark.parametrize(
    "invalid_phone",
    [
        "12345",                  # Missing country code +
        "not-a-number",           # Non-numeric
        "4155552671",             # US number without +
        "+1",                     # Too short (< 8 digits)
        "+12345678901234567",     # Too long (> 15 digits)
        "+",                      # Only plus
    ],
)
async def test_invalid_phone_numbers_rejected(invalid_phone):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "email": "invalid_test@example.com",
            "password": "SecurePassword123",
            "full_name": "Test User",
            "phone_number": invalid_phone,
            "role": "TECHNICIAN",
        }
        res = await client.post("/api/v1/auth/register", json=payload)
        assert res.status_code == 422  # Pydantic validation error


# ---------------------------------------------------------------------------
# Test 4: Existing email/password login continues to work
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_existing_email_password_login_continues_to_work(setup_test_db):
    db = setup_test_db
    await db.users.insert_one({
        "email": "legacy_admin@example.com",
        "hashed_password": hash_password("AdminPass123!"),
        "full_name": "Legacy Admin",
        "role": "ADMIN",
        "created_at": datetime.now(timezone.utc),
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_res = await client.post(
            "/api/v1/auth/login",
            data={"username": "legacy_admin@example.com", "password": "AdminPass123!"},
        )
        assert login_res.status_code == 200
        token_data = login_res.json()
        assert "access_token" in token_data
        assert token_data["token_type"] == "bearer"

        # Verify /me endpoint
        me_res = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["email"] == "legacy_admin@example.com"
        assert me_data["role"] == "ADMIN"
        assert me_data.get("phone_number") is None
        assert me_data.get("phone_verified") is False


# ---------------------------------------------------------------------------
# Test 5: Public registration cannot assign the Admin role
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_public_registration_cannot_assign_admin_role():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "email": "attacker@example.com",
            "password": "MaliciousPassword123",
            "full_name": "Wannabe Admin",
            "phone_number": "+14155552671",
            "role": "ADMIN",
        }
        res = await client.post("/api/v1/auth/register", json=payload)
        assert res.status_code == 400
        data = res.json()
        error_msg = data.get("error", {}).get("message") or data.get("detail", "")
        assert "Public registration cannot assign the Admin role" in error_msg


# ---------------------------------------------------------------------------
# Test 6: Duplicate phone number rejected
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_duplicate_phone_number_rejected(setup_test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload1 = {
            "email": "user1@example.com",
            "password": "Password123!",
            "full_name": "User One",
            "phone_number": "+14155552671",
            "role": "TECHNICIAN",
        }
        res1 = await client.post("/api/v1/auth/register", json=payload1)
        assert res1.status_code == 201

        payload2 = {
            "email": "user2@example.com",
            "password": "Password123!",
            "full_name": "User Two",
            "phone_number": "+14155552671",  # Same phone
            "role": "FACILITY_MANAGER",
        }
        res2 = await client.post("/api/v1/auth/register", json=payload2)
        assert res2.status_code == 409
        error_msg = res2.json().get("error", {}).get("message") or res2.json().get("detail", "")
        assert "Phone number already registered" in error_msg


# ---------------------------------------------------------------------------
# Test 7 & 8: TextBee High and Critical alerts trigger SMS to Admin
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_textbee_high_alert_triggers_sms_attempt_to_admin(setup_test_db):
    db = setup_test_db
    # Seed an Admin with phone number and a Technician with phone number
    await db.users.insert_one({
        "email": "main_admin@example.com",
        "hashed_password": hash_password("Pass123!"),
        "full_name": "Main Admin",
        "role": "ADMIN",
        "phone_number": "+919876543210",
        "phone_verified": False,
    })
    await db.users.insert_one({
        "email": "tech_worker@example.com",
        "hashed_password": hash_password("Pass123!"),
        "full_name": "Tech Worker",
        "role": "TECHNICIAN",
        "phone_number": "+919876543219",
        "phone_verified": False,
    })

    pipeline_result_high = {
        "severity": "High",
        "severity_confidence": 0.92,
        "anomaly_score": 0.85,
        "anomaly_flag": 1,
        "anomaly_duration": 45,
        "lstm_prob_24hr": 0.78,
        "lstm_prob_48hr": 0.91,
    }

    sent_recipients = []

    async def mock_textbee_send(recipient, title, message):
        sent_recipients.append(recipient)
        return True

    with patch.object(settings, "sms_provider", "textbee"), \
         patch.object(textbee_sms_provider, "is_configured", return_value=True), \
         patch.object(textbee_sms_provider, "send", side_effect=mock_textbee_send):
        alert = await evaluate_and_create_alert_from_pipeline_result(
            hvac_id="HVAC_SMS_UNIT_1",
            pipeline_result=pipeline_result_high,
        )
        assert alert is not None
        assert alert["severity"] == "PREDICTIVE"
        # Only the Admin's phone must receive the SMS, NOT technician
        assert sent_recipients == ["+919876543210"]


@pytest.mark.anyio
async def test_textbee_critical_alert_triggers_sms_attempt_to_admin(setup_test_db):
    db = setup_test_db
    await db.users.insert_one({
        "email": "admin_crit@example.com",
        "hashed_password": hash_password("Pass123!"),
        "full_name": "Emergency Admin",
        "role": "ADMIN",
        "phone_number": "+919876543211",
        "phone_verified": False,
    })

    pipeline_result_crit = {
        "severity": "Critical",
        "severity_confidence": 0.99,
        "anomaly_score": 0.95,
        "anomaly_flag": 1,
        "anomaly_duration": 90,
        "lstm_prob_24hr": 0.95,
        "lstm_prob_48hr": 0.99,
    }

    sent_recipients = []

    async def mock_textbee_send(recipient, title, message):
        sent_recipients.append(recipient)
        return True

    with patch.object(settings, "sms_provider", "textbee"), \
         patch.object(textbee_sms_provider, "is_configured", return_value=True), \
         patch.object(textbee_sms_provider, "send", side_effect=mock_textbee_send):
        alert = await evaluate_and_create_alert_from_pipeline_result(
            hvac_id="HVAC_SMS_UNIT_2",
            pipeline_result=pipeline_result_crit,
        )
        assert alert is not None
        assert alert["severity"] == "CRITICAL"
        assert sent_recipients == ["+919876543211"]


# ---------------------------------------------------------------------------
# Test 9: Low and Medium alerts do NOT trigger SMS
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_low_and_medium_alerts_do_not_trigger_sms(setup_test_db):
    db = setup_test_db
    await db.users.insert_one({
        "email": "admin_quiet@example.com",
        "hashed_password": hash_password("Pass123!"),
        "full_name": "Quiet Admin",
        "role": "ADMIN",
        "phone_number": "+919876543212",
        "phone_verified": False,
    })

    sent_recipients = []

    async def mock_textbee_send(recipient, title, message):
        sent_recipients.append(recipient)
        return True

    with patch.object(settings, "sms_provider", "textbee"), \
         patch.object(textbee_sms_provider, "is_configured", return_value=True), \
         patch.object(textbee_sms_provider, "send", side_effect=mock_textbee_send):
        # 1. Low severity -> No alert created, no SMS
        res_low = await evaluate_and_create_alert_from_pipeline_result(
            hvac_id="HVAC_SMS_LOW",
            pipeline_result={
                "severity": "Low",
                "severity_confidence": 0.88,
                "anomaly_score": 0.1,
                "anomaly_flag": 0,
                "anomaly_duration": 0,
                "lstm_prob_24hr": 0.05,
                "lstm_prob_48hr": 0.08,
            },
        )
        assert res_low is None
        assert len(sent_recipients) == 0

        # 2. Medium severity -> WARNING alert created, but MUST NOT send SMS
        res_med = await evaluate_and_create_alert_from_pipeline_result(
            hvac_id="HVAC_SMS_MED",
            pipeline_result={
                "severity": "Medium",
                "severity_confidence": 0.75,
                "anomaly_score": 0.45,
                "anomaly_flag": 0,
                "anomaly_duration": 10,
                "lstm_prob_24hr": 0.25,
                "lstm_prob_48hr": 0.35,
            },
        )
        assert res_med is not None
        assert res_med["severity"] == "WARNING"
        assert len(sent_recipients) == 0


# ---------------------------------------------------------------------------
# Test 10: Missing Admin phone is handled safely (no crash)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_missing_admin_phone_handled_safely(setup_test_db):
    db = setup_test_db
    await db.users.insert_one({
        "email": "nophone_admin@example.com",
        "hashed_password": hash_password("Pass123!"),
        "full_name": "No Phone Admin",
        "role": "ADMIN",
        # phone_number is intentionally omitted
    })

    with patch.object(textbee_sms_provider, "is_configured", return_value=True):
        alert = await evaluate_and_create_alert_from_pipeline_result(
            hvac_id="HVAC_NO_PHONE_UNIT",
            pipeline_result={
                "severity": "Critical",
                "severity_confidence": 0.95,
                "anomaly_score": 0.9,
                "anomaly_flag": 1,
                "anomaly_duration": 60,
                "lstm_prob_24hr": 0.9,
                "lstm_prob_48hr": 0.95,
            },
        )
        assert alert is not None
        assert alert["severity"] == "CRITICAL"


# ---------------------------------------------------------------------------
# Test 11: Missing TextBee configuration does not break alert creation
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_missing_textbee_config_does_not_break_alert(setup_test_db):
    db = setup_test_db
    await db.users.insert_one({
        "email": "admin_noconfig@example.com",
        "hashed_password": hash_password("Pass123!"),
        "full_name": "No Config Admin",
        "role": "ADMIN",
        "phone_number": "+919876543213",
    })

    with patch.object(textbee_sms_provider, "is_configured", return_value=False):
        alert = await evaluate_and_create_alert_from_pipeline_result(
            hvac_id="HVAC_UNCONFIGURED_TEXTBEE",
            pipeline_result={
                "severity": "High",
                "severity_confidence": 0.9,
                "anomaly_score": 0.8,
                "anomaly_flag": 1,
                "anomaly_duration": 40,
                "lstm_prob_24hr": 0.8,
                "lstm_prob_48hr": 0.85,
            },
        )
        assert alert is not None
        assert alert["severity"] == "PREDICTIVE"


# ---------------------------------------------------------------------------
# Test 12: TextBee provider network failure does not break alert storage
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_textbee_failure_does_not_break_alert_storage(setup_test_db):
    db = setup_test_db
    await db.users.insert_one({
        "email": "admin_failing_sms@example.com",
        "hashed_password": hash_password("Pass123!"),
        "full_name": "Failure Admin",
        "role": "ADMIN",
        "phone_number": "+919876543214",
    })

    async def failing_send(recipient, title, message):
        raise ConnectionError("Simulated Android device network timeout")

    with patch.object(textbee_sms_provider, "is_configured", return_value=True), \
         patch.object(textbee_sms_provider, "send", side_effect=failing_send):
        alert = await evaluate_and_create_alert_from_pipeline_result(
            hvac_id="HVAC_FAILING_PROVIDER",
            pipeline_result={
                "severity": "Critical",
                "severity_confidence": 0.97,
                "anomaly_score": 0.92,
                "anomaly_flag": 1,
                "anomaly_duration": 80,
                "lstm_prob_24hr": 0.9,
                "lstm_prob_48hr": 0.95,
            },
        )
        assert alert is not None
        # Verify it was stored in MongoDB despite gateway network error
        saved_alert = await db.alerts.find_one({"hvac_id": "HVAC_FAILING_PROVIDER"})
        assert saved_alert is not None
        assert saved_alert["severity"] == "CRITICAL"


# ---------------------------------------------------------------------------
# Test 13: Deduplication prevents duplicate alerts and duplicate SMS
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_duplicate_alerts_suppressed_no_duplicate_sms(setup_test_db):
    db = setup_test_db
    await db.users.insert_one({
        "email": "admin_dedup@example.com",
        "hashed_password": hash_password("Pass123!"),
        "full_name": "Dedup Admin",
        "role": "ADMIN",
        "phone_number": "+919876543215",
    })

    sms_count = 0

    async def counting_send(recipient, title, message):
        nonlocal sms_count
        sms_count += 1
        return True

    pipeline_input = {
        "severity": "High",
        "severity_confidence": 0.91,
        "anomaly_score": 0.82,
        "anomaly_flag": 1,
        "anomaly_duration": 35,
        "lstm_prob_24hr": 0.75,
        "lstm_prob_48hr": 0.85,
    }

    with patch.object(textbee_sms_provider, "is_configured", return_value=True), \
         patch.object(textbee_sms_provider, "send", side_effect=counting_send):
        # 1. First trigger -> alert created, SMS sent
        alert1 = await evaluate_and_create_alert_from_pipeline_result(
            hvac_id="HVAC_DEDUP_TEST",
            pipeline_result=pipeline_input,
        )
        assert alert1 is not None
        assert sms_count == 1

        # 2. Second trigger immediately after -> suppressed by 10-minute window!
        alert2 = await evaluate_and_create_alert_from_pipeline_result(
            hvac_id="HVAC_DEDUP_TEST",
            pipeline_result=pipeline_input,
        )
        assert alert2 is None  # Suppressed!
        assert sms_count == 1  # No duplicate SMS!


# ---------------------------------------------------------------------------
# Test 14: Twilio provider still works when selected via settings.sms_provider
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_twilio_fallback_when_selected(setup_test_db):
    db = setup_test_db
    await db.users.insert_one({
        "email": "admin_twilio@example.com",
        "hashed_password": hash_password("Pass123!"),
        "full_name": "Twilio Admin",
        "role": "ADMIN",
        "phone_number": "+14155554444",
    })

    twilio_sent = []

    def mock_twilio_sync(to_number, body):
        twilio_sent.append(to_number)
        mock_msg = MagicMock()
        mock_msg.sid = "SM_TWILIO_OK"
        mock_msg.status = "queued"
        return mock_msg

    with patch.object(settings, "sms_provider", "twilio"), \
         patch.object(twilio_sms_provider, "is_configured", return_value=True), \
         patch.object(twilio_sms_provider, "_send_sync", side_effect=mock_twilio_sync):
        alert = await evaluate_and_create_alert_from_pipeline_result(
            hvac_id="HVAC_TWILIO_UNIT",
            pipeline_result={
                "severity": "Critical",
                "severity_confidence": 0.99,
                "anomaly_score": 0.95,
                "anomaly_flag": 1,
                "anomaly_duration": 60,
                "lstm_prob_24hr": 0.95,
                "lstm_prob_48hr": 0.99,
            },
        )
        assert alert is not None
        assert twilio_sent == ["+14155554444"]


# ---------------------------------------------------------------------------
# Test 15: Masking phone numbers in logs
# ---------------------------------------------------------------------------
def test_mask_phone_number():
    assert mask_phone_number("+14155552671") == "+14***2671"
    assert mask_phone_number("+919876543210") == "+91***3210"
    assert mask_phone_number("12345") == "12***"
    assert mask_phone_number("") == "***"
