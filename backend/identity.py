"""Resolve the requesting user.

  prod (IDENTITY_SOURCE=iap): trust the IAP-signed header
    X-Goog-Authenticated-User-Email: accounts.google.com:alice@corp.com
  demo (IDENTITY_SOURCE=demo): a persona switcher sends X-Demo-User: alice@corp.com
"""
import config


def resolve(headers):
    if config.IDENTITY_SOURCE == "iap":
        raw = headers.get("x-goog-authenticated-user-email", "")
        return raw.split(":")[-1].strip() if raw else ""
    return headers.get("x-demo-user", "").strip()
