import unittest

from app.services.care_engine import (
    _rule_based_reply,
    INTENT_ACTIONS,
    _rag_snippet,
    _tx_context_line,
    _extract_transaction_ref,
    _wants_transaction_detail_lookup,
)


class _MockChunk:
    def __init__(self, content: str, category: str = "general"):
        self.content = content
        self.category = category


def _chunk(content: str, category: str = "general"):
    return _MockChunk(content, category)


class TestRagSnippet(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_rag_snippet([]), "")

    def test_with_content(self):
        chunks = [_chunk("Our balance info is in the app.")]
        self.assertIn("Our balance info", _rag_snippet(chunks))

    def test_truncates(self):
        chunks = [_chunk("x" * 300)]
        out = _rag_snippet(chunks, max_len=50)
        self.assertEqual(len(out), 53)
        self.assertTrue(out.endswith("..."))


class TestTxContext(unittest.TestCase):
    def test_no_transactions(self):
        self.assertEqual(_tx_context_line({"recent_transactions": []}), "")
        self.assertEqual(_tx_context_line({}), "")

    def test_with_transactions(self):
        ctx = {
            "recent_transactions": [
                {"amount": 50, "currency": "GHS", "merchant": "Shop A"},
                {"amount": 20, "currency": "GHS", "merchant": None},
            ]
        }
        line = _tx_context_line(ctx, max_items=2)
        self.assertIn("Your recent activity includes", line)
        self.assertIn("50 GHS at Shop A", line)
        self.assertIn("20 GHS at merchant", line)


class TestTransactionRefExtract(unittest.TestCase):
    def test_plain_external_id(self):
        self.assertEqual(_extract_transaction_ref("ABC-12345"), "ABC-12345")

    def test_uuid_embedded(self):
        u = "550e8400-e29b-41d4-a716-446655440000"
        self.assertEqual(_extract_transaction_ref(f"please check {u} thanks"), u)

    def test_transaction_id_prefix(self):
        self.assertEqual(_extract_transaction_ref("Transaction id: TX-999"), "TX-999")


class TestWantsTransactionDetailLookup(unittest.TestCase):
    def test_money_gone_triggers(self):
        self.assertTrue(_wants_transaction_detail_lookup("My money is gone"))

    def test_unauthorised_payment_triggers(self):
        self.assertTrue(_wants_transaction_detail_lookup("unauthorised payment"))

    def test_unauthorized_charge_triggers(self):
        self.assertTrue(_wants_transaction_detail_lookup("unauthorized charge on my card"))

    def test_list_blocked(self):
        self.assertFalse(_wants_transaction_detail_lookup("show my transactions this week"))


class TestRuleBasedReply(unittest.TestCase):
    def test_balance_intent_and_actions(self):
        reply, intent, actions, escalate = _rule_based_reply(
            "What is my balance?",
            {"has_customer": True},
            [],
            [],
        )
        self.assertEqual(intent, "BALANCE_INQUIRY")
        self.assertEqual(actions, INTENT_ACTIONS["BALANCE_INQUIRY"])
        self.assertFalse(escalate)
        self.assertIn("balance", reply.lower())

    def test_balance_with_rag(self):
        chunks = [_chunk("Balances are updated every 5 minutes.")]
        reply, _, _, _ = _rule_based_reply(
            "check balance",
            {"has_customer": True},
            [],
            chunks,
        )
        self.assertIn("According to our information", reply)
        self.assertIn("Balances are updated", reply)

    def test_fraud_intent_and_actions(self):
        reply, intent, actions, escalate = _rule_based_reply(
            "I see a fraudulent charge",
            {"has_customer": True},
            [],
            [],
        )
        self.assertEqual(intent, "FRAUD_DISPUTE")
        self.assertEqual(actions, INTENT_ACTIONS["FRAUD_DISPUTE"])
        self.assertIn("dispute", reply.lower())

    def test_fraud_with_tx_context(self):
        ctx = {
            "has_customer": True,
            "recent_transactions": [
                {"amount": 100, "currency": "GHS", "merchant": "Unknown"},
            ],
        }
        reply, _, _, _ = _rule_based_reply("dispute this transaction", ctx, [], [])
        self.assertIn("Your recent activity includes", reply)
        self.assertIn("100 GHS at Unknown", reply)

    def test_fraud_with_rag(self):
        chunks = [_chunk("Disputes are reviewed within 5 business days.")]
        reply, _, _, _ = _rule_based_reply("chargeback", {"has_customer": True}, [], chunks)
        self.assertIn("Policy note", reply)
        self.assertIn("Disputes are reviewed", reply)

    def test_escalation_confirm_from_history(self):
        history = [
            {"role": "user", "content": "I want to speak to someone"},
            {"role": "assistant", "content": "I can escalate this to a human agent for you. Reply 'yes' if you want me to escalate now."},
        ]
        reply, intent, actions, escalate = _rule_based_reply(
            "yes please",
            {"has_customer": True},
            history,
            [],
        )
        self.assertTrue(escalate)
        self.assertEqual(intent, "HUMAN_ESCALATION")
        self.assertIn("escalated", reply.lower())

    def test_card_block_intent(self):
        reply, intent, actions, _ = _rule_based_reply(
            "I need to block my card",
            {"has_customer": True},
            [],
            [],
        )
        self.assertEqual(intent, "CARD_BLOCK")
        self.assertTrue(set(INTENT_ACTIONS["CARD_BLOCK"]).issubset(set(actions)))
        self.assertIn("block", reply.lower())

    def test_pin_reset_intent(self):
        reply, intent, actions, _ = _rule_based_reply(
            "how do I reset my pin?",
            {"has_customer": True},
            [],
            [],
        )
        self.assertEqual(intent, "PIN_RESET")
        self.assertTrue(set(INTENT_ACTIONS["PIN_RESET"]).issubset(set(actions)))

    def test_branch_atm_intent(self):
        reply, intent, actions, _ = _rule_based_reply(
            "where is the nearest branch?",
            {"has_customer": True},
            [],
            [],
        )
        self.assertEqual(intent, "BRANCH_ATM")
        self.assertEqual(actions, INTENT_ACTIONS["BRANCH_ATM"])

    def test_complaint_intent(self):
        reply, intent, actions, _ = _rule_based_reply(
            "I have a complaint about the service",
            {"has_customer": True},
            [],
            [],
        )
        self.assertEqual(intent, "COMPLAINT")
        self.assertEqual(actions, INTENT_ACTIONS["COMPLAINT"])
        self.assertIn("complaint", reply.lower())

    def test_transaction_history_with_tx_context(self):
        ctx = {
            "has_customer": True,
            "recent_transactions": [
                {"amount": 30, "currency": "GHS", "merchant": "Vendor"},
            ],
        }
        reply, intent, _, _ = _rule_based_reply("show recent transactions", ctx, [], [])
        self.assertEqual(intent, "TRANSACTION_HISTORY")
        self.assertIn("Your recent activity includes", reply)
        self.assertIn("30 GHS at Vendor", reply)

    def test_no_customer_fallback(self):
        reply, intent, actions, _ = _rule_based_reply(
            "random question",
            {"has_customer": False},
            [],
            [],
        )
        self.assertIn(intent, {"GENERAL_SUPPORT", "SECURITY_GUIDANCE"})
        self.assertTrue("did you mean" in reply.lower() or "customer profile" in reply.lower())

    def test_general_support_has_actions(self):
        _, intent, actions, _ = _rule_based_reply(
            "hello",
            {"has_customer": True},
            [],
            [],
        )
        self.assertEqual(intent, "GENERAL_SUPPORT")
        self.assertTrue(len(actions) > 0)

    def test_general_chat_greeting(self):
        reply, intent, _, _ = _rule_based_reply(
            "hello",
            {"has_customer": True},
            [],
            [],
        )
        self.assertEqual(intent, "GENERAL_SUPPORT")
        self.assertIn("Hi", reply)
        self.assertIn("help", reply.lower())

    def test_general_chat_what_can_you_do(self):
        reply, intent, _, _ = _rule_based_reply(
            "what can you do",
            {"has_customer": True},
            [],
            [],
        )
        self.assertEqual(intent, "GENERAL_SUPPORT")
        self.assertIn("balance", reply.lower())

    def test_out_of_scope_states_purpose(self):
        reply, intent, _, _ = _rule_based_reply(
            "what is the capital of france",
            {"has_customer": True},
            [],
            [],
        )
        self.assertIn(intent, {"GENERAL_SUPPORT", "BALANCE_INQUIRY"})
        self.assertTrue(
            ("virtual assistant" in reply.lower() and "outside" in reply.lower()) or ("did you mean" in reply.lower())
        )


if __name__ == "__main__":
    unittest.main()
