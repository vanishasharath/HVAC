import asyncio
import logging
from abc import ABC, abstractmethod

import httpx

from app.config import settings

logger = logging.getLogger("notifications")


def mask_phone_number(phone: str) -> str:
    """Mask phone number for safe logging (e.g. +14155552671 -> +14***2671)."""
    if not phone:
        return "***"
    cleaned = str(phone).strip()
    if len(cleaned) <= 6:
        return cleaned[:2] + "***"
    return f"{cleaned[:3]}***{cleaned[-4:]}"


class NotificationProvider(ABC):
    @abstractmethod
    async def send(self, recipient: str, title: str, message: str) -> bool:
        raise NotImplementedError


class FCMProvider(NotificationProvider):
    async def send(self, recipient: str, title: str, message: str) -> bool:
        logger.info("FCM not configured - would send push to %s: [%s] %s", recipient, title, message)
        return False


class SNSProvider(NotificationProvider):
    async def send(self, recipient: str, title: str, message: str) -> bool:
        logger.info("SNS not configured - would send SMS/email to %s: [%s] %s", recipient, title, message)
        return False


class TextBeeSMSProvider(NotificationProvider):
    """
    TextBee SMS notification provider.
    Dispatches SMS via connected Android gateway device using TextBee's REST API.
    Runs asynchronously via httpx without blocking the FastAPI event loop.
    """

    API_URL = "https://api.textbee.dev/api/v1/gateway/send-sms"

    def is_configured(self) -> bool:
        api_key = settings.textbee_api_key
        if not api_key:
            return False
        placeholders = ["your_textbee_api_key_here", "placeholder"]
        if api_key in placeholders:
            return False
        return True

    async def send(self, recipient: str, title: str, message: str) -> bool:
        if not recipient or not recipient.startswith("+"):
            return False

        masked = mask_phone_number(recipient)

        if not self.is_configured():
            logger.info(
                "TextBee SMS not configured (missing or placeholder TEXTBEE_API_KEY) - skipping SMS to %s: [%s] %s",
                masked,
                title,
                message,
            )
            return False

        body_text = f"[{title}]\n{message}" if title else message

        payload = {
            "recipients": [recipient],
            "message": body_text,
        }
        if settings.textbee_device_id and settings.textbee_device_id.strip():
            device_id = settings.textbee_device_id.strip()
            if device_id != "your_textbee_device_id_here":
                payload["deviceId"] = device_id

        headers = {
            "x-api-key": settings.textbee_api_key,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.API_URL, json=payload, headers=headers)

            if response.status_code in (200, 201):
                try:
                    res_json = response.json()
                    if res_json.get("success") is False or "error" in res_json:
                        logger.error(
                            "TextBee gateway returned failure for %s: %s",
                            masked,
                            res_json.get("error") or res_json,
                        )
                        return False
                    data_obj = res_json.get("data", {})
                    if isinstance(data_obj, dict) and data_obj.get("success") is False:
                        logger.error(
                            "TextBee gateway returned failure for %s: %s",
                            masked,
                            data_obj.get("message") or res_json,
                        )
                        return False
                except Exception:
                    pass

                logger.info(
                    "TextBee SMS accepted for %s (Status: %s, Response: %s)",
                    masked,
                    response.status_code,
                    response.text[:200],
                )
                return True
            else:
                logger.error(
                    "TextBee SMS request for %s rejected by gateway (Status: %s, Response: %s)",
                    masked,
                    response.status_code,
                    response.text[:300],
                )
                return False
        except Exception as exc:
            logger.error("TextBee SMS dispatch to %s failed: %s", masked, exc)
            return False


class TwilioSMSProvider(NotificationProvider):
    """
    Twilio SMS notification provider.
    Sends SMS messages asynchronously using asyncio.to_thread to avoid blocking
    the FastAPI event loop.
    """

    def is_configured(self) -> bool:
        sid = settings.twilio_account_sid
        token = settings.twilio_auth_token
        from_num = settings.twilio_from_number
        if not sid or not token or not from_num:
            return False
        # Guard against placeholder values
        placeholders = ["your_twilio_account_sid_here", "your_twilio_auth_token_here", "placeholder"]
        if sid in placeholders or token in placeholders:
            return False
        return True

    def _send_sync(self, to_number: str, body: str):
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        return client.messages.create(
            body=body,
            from_=settings.twilio_from_number,
            to=to_number,
        )

    async def send(self, recipient: str, title: str, message: str) -> bool:
        if not recipient or not recipient.startswith("+"):
            return False

        masked = mask_phone_number(recipient)

        if not self.is_configured():
            logger.info(
                "Twilio SMS not configured - skipping SMS dispatch to %s: [%s] %s",
                masked,
                title,
                message,
            )
            return False

        body_text = f"[{title}]\n{message}" if title else message

        try:
            msg = await asyncio.to_thread(self._send_sync, recipient, body_text)
            logger.info(
                "Twilio SMS accepted by provider for %s (SID: %s, Status: %s)",
                masked,
                getattr(msg, "sid", "unknown"),
                getattr(msg, "status", "accepted"),
            )
            return True
        except Exception as exc:
            logger.error("Twilio SMS dispatch to %s failed: %s", masked, exc)
            return False


class NotificationService:
    def __init__(self, providers: list):
        self.providers = providers

    async def notify(self, recipient: str, title: str, message: str) -> dict:
        results = {}
        for provider in self.providers:
            name = type(provider).__name__
            try:
                success = await provider.send(recipient, title, message)
                results[name] = "sent" if success else "not_configured"
            except Exception as exc:
                logger.error("Notification provider %s failed: %s", name, exc)
                results[name] = "failed"
        return results

    async def send_sms(self, recipient: str, title: str, message: str) -> bool:
        """Dedicated method for sending SMS to a normalized phone number via configured provider."""
        provider_choice = (settings.sms_provider or "textbee").strip().lower()

        if provider_choice == "textbee":
            return await textbee_sms_provider.send(recipient, title, message)
        elif provider_choice == "twilio":
            return await twilio_sms_provider.send(recipient, title, message)
        else:
            # Fallback: try active configured provider
            if textbee_sms_provider.is_configured():
                return await textbee_sms_provider.send(recipient, title, message)
            elif twilio_sms_provider.is_configured():
                return await twilio_sms_provider.send(recipient, title, message)
            return False


textbee_sms_provider = TextBeeSMSProvider()
twilio_sms_provider = TwilioSMSProvider()

notification_service = NotificationService(
    providers=[FCMProvider(), SNSProvider()]
)
