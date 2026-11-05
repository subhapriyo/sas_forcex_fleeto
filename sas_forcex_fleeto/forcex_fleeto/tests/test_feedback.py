"""Phase 4 — customer feedback desk: versions, FIFO queue, retries (Screens 7-9)."""

import datetime as dt
import unittest

from sas_forcex_fleeto.forcex_fleeto.services import feedback as fb
from sas_forcex_fleeto.forcex_fleeto.services.constants import AnswerType
from sas_forcex_fleeto.forcex_fleeto.services.constants import CallOutcome as O
from sas_forcex_fleeto.forcex_fleeto.services.constants import CallStatus as CS


def v(code, frm, to=None, status="Active", responses=0):
    return fb.QuestionnaireVersion(code=code, effective_from=frm, effective_to=to, status=status, response_count=responses)


class TestVersions(unittest.TestCase):
    def setUp(self):
        self.versions = [
            v("FB-Q-2026-01", dt.date(2026, 4, 1), dt.date(2026, 9, 30), responses=412),
            v("FB-Q-2026-02", dt.date(2026, 10, 1)),
            v("FB-Q-2026-03", dt.date(2026, 12, 1), status="Draft"),
        ]

    def test_picks_version_effective_on_call_date(self):
        self.assertEqual(fb.effective_version(self.versions, dt.date(2026, 9, 30)).code, "FB-Q-2026-01")
        self.assertEqual(fb.effective_version(self.versions, dt.date(2026, 10, 1)).code, "FB-Q-2026-02")

    def test_draft_versions_are_ignored(self):
        self.assertEqual(fb.effective_version(self.versions, dt.date(2026, 12, 5)).code, "FB-Q-2026-02")

    def test_no_version_raises(self):
        with self.assertRaises(fb.FeedbackError):
            fb.effective_version(self.versions, dt.date(2026, 1, 1))

    def test_activating_new_version_closes_previous_day_before(self):
        prev = v("FB-Q-2026-02", dt.date(2026, 10, 1))
        fb.close_previous(prev, new_from=dt.date(2027, 1, 1))
        self.assertEqual(prev.effective_to, dt.date(2026, 12, 31))

    def test_new_version_cannot_start_before_previous(self):
        with self.assertRaises(fb.FeedbackError):
            fb.close_previous(v("X", dt.date(2026, 10, 1)), new_from=dt.date(2026, 10, 1))

    def test_version_with_responses_is_read_only(self):
        self.assertTrue(fb.is_read_only(self.versions[0]))
        self.assertFalse(fb.is_read_only(self.versions[1]))


class TestQueue(unittest.TestCase):
    def setUp(self):
        self.invoices = [
            fb.InvoiceForCall("INV-4405", dt.date(2026, 10, 3)),
            fb.InvoiceForCall("INV-4391", dt.date(2026, 9, 30)),
            fb.InvoiceForCall("INV-4398", dt.date(2026, 10, 2)),
            fb.InvoiceForCall("INV-4410", dt.date(2026, 10, 5)),
            fb.InvoiceForCall("INV-4420", dt.date(2026, 10, 8)),  # not yet due
        ]

    def test_due_date_is_invoice_plus_call_after(self):
        self.assertEqual(fb.call_due_date(dt.date(2026, 9, 30), 7), dt.date(2026, 10, 7))

    def test_queue_contains_only_due_invoices_without_a_call(self):
        due = fb.invoices_to_enqueue(self.invoices, call_after_days=7, today=dt.date(2026, 10, 12),
                                     already_queued={"INV-4398"})
        self.assertEqual([i.invoice_no for i in due], ["INV-4391", "INV-4405", "INV-4410"])

    def test_next_call_is_oldest_callable(self):
        now = dt.datetime(2026, 10, 12, 10, 0)
        calls = [
            fb.QueuedCall("INV-4405", dt.date(2026, 10, 3), CS.QUEUED),
            fb.QueuedCall("INV-4391", dt.date(2026, 9, 30), CS.ON_HOLD, hold_until=dt.datetime(2026, 10, 12, 16, 0)),
            fb.QueuedCall("INV-4398", dt.date(2026, 10, 2), CS.QUEUED),
            fb.QueuedCall("INV-4380", dt.date(2026, 9, 20), CS.COMPLETED),
        ]
        self.assertEqual(fb.next_call(calls, now).invoice_no, "INV-4398")

    def test_held_call_returns_to_front_after_hold(self):
        calls = [
            fb.QueuedCall("INV-4398", dt.date(2026, 10, 2), CS.QUEUED),
            fb.QueuedCall("INV-4391", dt.date(2026, 9, 30), CS.ON_HOLD, hold_until=dt.datetime(2026, 10, 12, 16, 0)),
        ]
        self.assertEqual(fb.next_call(calls, dt.datetime(2026, 10, 12, 16, 1)).invoice_no, "INV-4391")

    def test_empty_queue_returns_none(self):
        self.assertIsNone(fb.next_call([], dt.datetime(2026, 10, 12)))


class TestAttempts(unittest.TestCase):
    def test_not_reachable_requeues_until_max(self):
        c = fb.QueuedCall("INV-1", dt.date(2026, 9, 30), CS.QUEUED)
        fb.register_attempt(c, O.NOT_REACHABLE, max_attempts=3)
        fb.register_attempt(c, O.NOT_REACHABLE, max_attempts=3)
        self.assertEqual((c.status, c.attempts), (CS.QUEUED, 2))
        fb.register_attempt(c, O.NOT_REACHABLE, max_attempts=3)
        self.assertEqual((c.status, c.attempts), (CS.UNREACHABLE, 3))

    def test_call_back_later_requires_a_time(self):
        c = fb.QueuedCall("INV-1", dt.date(2026, 9, 30), CS.QUEUED)
        with self.assertRaises(fb.FeedbackError):
            fb.register_attempt(c, O.CALL_BACK_LATER, max_attempts=3)
        fb.register_attempt(c, O.CALL_BACK_LATER, max_attempts=3, callback_at=dt.datetime(2026, 10, 13, 11))
        self.assertEqual(c.status, CS.ON_HOLD)

    def test_declined_closes_call(self):
        c = fb.QueuedCall("INV-1", dt.date(2026, 9, 30), CS.QUEUED)
        fb.register_attempt(c, O.DECLINED, max_attempts=3)
        self.assertEqual(c.status, CS.DECLINED)

    def test_closed_call_cannot_be_attempted_again(self):
        c = fb.QueuedCall("INV-1", dt.date(2026, 9, 30), CS.COMPLETED)
        with self.assertRaises(fb.FeedbackError):
            fb.register_attempt(c, O.NOT_REACHABLE, max_attempts=3)


class TestAnswers(unittest.TestCase):
    def setUp(self):
        self.questions = [
            fb.Question(1, "How would you rate our service?", AnswerType.STAR, mandatory=True),
            fb.Question(2, "How would you rate our product?", AnswerType.STAR, mandatory=True),
            fb.Question(3, "Would you recommend our product to others?", AnswerType.YES_NO_MAYBE, mandatory=True,
                        is_recommend_question=True),
            fb.Question(5, "Any suggestions for us?", AnswerType.TEXT, mandatory=False),
        ]

    def test_missing_mandatory_answers(self):
        self.assertEqual(fb.missing_mandatory(self.questions, {1: 4}), [2, 3])

    def test_invalid_star_value_rejected(self):
        with self.assertRaises(fb.FeedbackError):
            fb.validate_answers(self.questions, {1: 6, 2: 5, 3: "Yes"})

    def test_detractor_on_low_star(self):
        self.assertTrue(fb.is_detractor(self.questions, {1: 2, 2: 5, 3: "Yes"}))

    def test_detractor_on_no_recommend(self):
        self.assertTrue(fb.is_detractor(self.questions, {1: 5, 2: 5, 3: "No"}))

    def test_promoter_is_not_detractor(self):
        self.assertFalse(fb.is_detractor(self.questions, {1: 4, 2: 5, 3: "Maybe"}))


class TestWhatsAppTemplate(unittest.TestCase):
    TEMPLATE = ("Dear {customer_name}, thank you for sharing your feedback with FLEETO Customer Care "
                "today on invoice {invoice_no}. We value your opinion. — Team FLEETO")

    def test_render(self):
        msg = fb.render_message(self.TEMPLATE, {"customer_name": "Anupam Das", "invoice_no": "INV-2026-4391"})
        self.assertIn("Dear Anupam Das", msg)
        self.assertIn("INV-2026-4391", msg)

    def test_unknown_placeholder_is_reported(self):
        with self.assertRaises(fb.FeedbackError) as ctx:
            fb.render_message("Hi {customer_name} {dealer}", {"customer_name": "A"})
        self.assertIn("dealer", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
