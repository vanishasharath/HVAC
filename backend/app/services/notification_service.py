import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("notifications")


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


notification_service = NotificationService(providers=[FCMProvider(), SNSProvider()])
