"""WhatsApp rules: phone numbers and Meta Cloud API payloads (no database)."""

import unittest

from sas_forcex_fleeto.forcex_fleeto.services.whatsapp_rules import (
    InvalidNumber,
    cloud_api_url,
    cloud_error_text,
    template_payload,
    text_payload,
    to_whatsapp_number,
)


class TestNumbers(unittest.TestCase):
    def test_ten_digit_indian_mobile_gets_country_code(self):
        self.assertEqual(to_whatsapp_number("9830012345"), "919830012345")

    def test_spaces_dashes_plus_and_leading_zero_are_removed(self):
        self.assertEqual(to_whatsapp_number("+91 98300-12345"), "919830012345")
        self.assertEqual(to_whatsapp_number("09830012345"), "919830012345")

    def test_number_that_already_has_country_code_is_kept(self):
        self.assertEqual(to_whatsapp_number("919830012345"), "919830012345")

    def test_other_default_country_code(self):
        self.assertEqual(to_whatsapp_number("1712345678", default_cc="880"), "8801712345678")

    def test_blank_or_too_short_is_rejected(self):
        for bad in ("", None, "12345", "abc"):
            with self.assertRaises(InvalidNumber):
                to_whatsapp_number(bad)


class TestPayloads(unittest.TestCase):
    def test_url(self):
        self.assertEqual(cloud_api_url("v21.0", "1234"), "https://graph.facebook.com/v21.0/1234/messages")
        self.assertEqual(cloud_api_url("21.0", "1234"), "https://graph.facebook.com/v21.0/1234/messages")

    def test_text_payload(self):
        self.assertEqual(text_payload("919830012345", "Hello"), {
            "messaging_product": "whatsapp", "to": "919830012345", "type": "text",
            "text": {"preview_url": False, "body": "Hello"}})

    def test_template_payload_with_body_parameters(self):
        p = template_payload("919830012345", "fx_booking_alert", "en", ["T-1", "", None, 5])
        self.assertEqual(p["type"], "template")
        self.assertEqual(p["template"]["name"], "fx_booking_alert")
        self.assertEqual(p["template"]["language"], {"code": "en"})
        # Meta rejects empty parameters, so blanks become "-"
        self.assertEqual([x["text"] for x in p["template"]["components"][0]["parameters"]],
                         ["T-1", "-", "-", "5"])

    def test_template_without_parameters_has_no_components(self):
        p = template_payload("919830012345", "hello_world", "en_US")
        self.assertNotIn("components", p["template"])

    def test_error_text_from_meta_response(self):
        body = {"error": {"message": "Invalid OAuth access token", "code": 190}}
        self.assertEqual(cloud_error_text(body), "Invalid OAuth access token (code 190)")
        self.assertEqual(cloud_error_text("not json"), "not json")
