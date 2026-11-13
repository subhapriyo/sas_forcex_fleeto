"""
WhatsApp rules — pure Python, no frappe import, unit-tested.

Meta WhatsApp Cloud API basics this module encodes:
  * Numbers go out as digits only, with country code, no "+" (e.g. 919830012345).
  * POST https://graph.facebook.com/<version>/<phone-number-id>/messages
  * A business-started message (our booking alert, the feedback thank-you) must
    use a TEMPLATE that Meta has approved. Plain text is delivered only inside the
    24-hour window after the customer last wrote to you. That is why every event
    in FX WhatsApp Settings has its own template name.
"""

from __future__ import annotations

import re


class InvalidNumber(ValueError):
    pass


def to_whatsapp_number(raw: str | None, default_cc: str = "91") -> str:
    """'+91 98300-12345' / '09830012345' / '9830012345' -> '919830012345'."""
    digits = re.sub(r"\D", "", raw or "")
    cc = re.sub(r"\D", "", default_cc or "")
    if digits.startswith("00"):          # 00 international prefix
        digits = digits[2:]
    elif digits.startswith("0"):         # trunk prefix: 0 + local number
        digits = cc + digits.lstrip("0")
    if len(digits) == 10:                # local mobile without country code
        digits = cc + digits
    if not 11 <= len(digits) <= 15:      # E.164 allows at most 15 digits
        raise InvalidNumber(f"'{raw}' is not a usable WhatsApp number")
    return digits


def cloud_api_url(version: str, phone_number_id: str) -> str:
    version = version if (version or "").startswith("v") else f"v{version}"
    return f"https://graph.facebook.com/{version}/{phone_number_id}/messages"


def text_payload(to: str, body: str) -> dict:
    return {"messaging_product": "whatsapp", "to": to, "type": "text",
            "text": {"preview_url": False, "body": body}}


def template_payload(to: str, name: str, language: str, params: list | None = None) -> dict:
    """Template message; `params` fill {{1}}, {{2}}... of the template BODY in order."""
    template = {"name": name, "language": {"code": language}}
    if params:
        # Meta rejects an empty parameter, so a missing value is sent as "-"
        template["components"] = [{"type": "body", "parameters": [
            {"type": "text", "text": str(p) if p not in (None, "") else "-"} for p in params]}]
    return {"messaging_product": "whatsapp", "to": to, "type": "template", "template": template}


def cloud_error_text(body) -> str:
    """Readable error from a Cloud API error response (dict) or raw text."""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        e = body["error"]
        return f"{e.get('message', 'Unknown error')} (code {e.get('code', '?')})"
    return str(body)[:300]
