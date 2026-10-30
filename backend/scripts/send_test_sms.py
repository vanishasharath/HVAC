"""
Interactive / CLI script to send a single test SMS via the configured
gateway (TextBee or Twilio) to verify connectivity before testing alerts.

Usage:
    python scripts/send_test_sms.py --phone +91XXXXXXXXXX
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add backend directory to sys.path so app imports work
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import settings
from app.schemas.user import normalize_phone_number
from app.services.notification_service import (
    mask_phone_number,
    notification_service,
    textbee_sms_provider,
    twilio_sms_provider,
)


async def main():
    parser = argparse.ArgumentParser(description="Send a test SMS via TextBee/Twilio")
    parser.add_argument(
        "--phone",
        type=str,
        help="Recipient phone number with country code (e.g. +919876543210)",
        required=False,
    )
    args = parser.parse_args()

    phone = args.phone
    if not phone:
        phone = input("Enter destination phone number (with country code, e.g. +919876543210): ").strip()

    try:
        normalized_phone = normalize_phone_number(phone)
    except ValueError as err:
        print(f"\n[ERROR] Invalid phone number format: {err}")
        sys.exit(1)

    provider = (settings.sms_provider or "textbee").strip().lower()
    print("\n" + "=" * 60)
    print(" HVAC SYSTEM — SMS GATEWAY TEST UTILITY ")
    print("=" * 60)
    print(f"Active Provider:    {provider.upper()}")
    print(f"Target Recipient:   {mask_phone_number(normalized_phone)} ({normalized_phone})")

    if provider == "textbee":
        configured = textbee_sms_provider.is_configured()
        print(f"API Key Set:        {'YES' if settings.textbee_api_key else 'NO'}")
        print(f"Device ID Set:      {settings.textbee_device_id or '(Default device will be used)'}")
    else:
        configured = twilio_sms_provider.is_configured()
        print(f"Twilio SID Set:     {'YES' if settings.twilio_account_sid else 'NO'}")
        print(f"From Number:        {settings.twilio_from_number or 'NOT SET'}")

    if not configured:
        print("\n[WARNING] Selected provider is NOT fully configured in backend/.env!")
        if provider == "textbee":
            print("Please add TEXTBEE_API_KEY=your_key to backend/.env and restart.")
        else:
            print("Please add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER to backend/.env.")
        sys.exit(1)

    title = "HVAC SYSTEM TEST"
    message = "Test SMS from your Smart HVAC Leak Detection System. Gateway is connected and operational!"

    print(f"\nSending test SMS...")
    success = await notification_service.send_sms(
        recipient=normalized_phone,
        title=title,
        message=message,
    )

    if success:
        print("\n[SUCCESS] Test SMS accepted by the gateway!")
        print("Check your mobile device to verify delivery.")
    else:
        print("\n[FAILED] Test SMS could not be dispatched.")
        print("Check backend logs or verify that your Android device / SIM card has cellular service.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
