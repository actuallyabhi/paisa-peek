"""Web Push: the VAPID key pair lives in DATA_DIR (generated once); send() fans out to every subscribed device."""

import base64
import json
import logging

from cryptography.hazmat.primitives import serialization
from django.conf import settings
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from requests import RequestException

from .models import PushSubscription

log = logging.getLogger(__name__)


def _vapid() -> Vapid:
    path = settings.DATA_DIR / "vapid_private.pem"
    if not path.exists():
        v = Vapid()
        v.generate_keys()
        v.save_key(str(path))
        path.chmod(0o600)
    return Vapid.from_file(str(path))


def public_key() -> str:
    """applicationServerKey for pushManager.subscribe()."""
    raw = _vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def send(title: str, body: str, url: str = "/") -> int:
    """Notify all devices; drops subscriptions the push service says are gone. Returns devices reached."""
    vapid, sent = _vapid(), 0
    for sub in PushSubscription.objects.all():
        try:
            webpush(
                {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=vapid, vapid_claims={"sub": settings.VAPID_SUBJECT}, ttl=12 * 3600,
            )
            sent += 1
        except WebPushException as e:
            if e.response is not None and e.response.status_code in (404, 410):
                sub.delete()  # uninstalled / permission revoked
            else:
                log.warning("push to %s failed: %s", sub.endpoint[:60], e)
        except RequestException as e:  # push service unreachable: skip this device, keep going
            log.warning("push to %s failed: %s", sub.endpoint[:60], e)
    return sent
