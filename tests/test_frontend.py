import ast
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
CONTRACT = open(os.path.join(ROOT, "contract.py"), encoding="utf-8").read()
SCRIPT = re.search(r'<script type="module">(.*?)</script>', HTML, re.S).group(1)


def methods(public_only=True):
    tree = ast.parse(CONTRACT)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AnswerArena")
    return {n.name for n in cls.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}


def params_of(name):
    sig = re.search(r"def %s\((.*?)\) -> str" % name, CONTRACT, re.S).group(1)
    return [p.strip().split(":")[0].split("=")[0].strip() for p in sig.split(",") if p.strip() and p.strip() != "self"]


class TestFrontend(unittest.TestCase):
    def test_single_module_script_from_esm_sh(self):
        self.assertIn('from "https://esm.sh/genlayer-js@latest"', HTML)
        self.assertIn('from "https://esm.sh/genlayer-js@latest/chains"', HTML)
        self.assertEqual(len(re.findall(r'<script type="module">', HTML)), 1)
        for inline in re.findall(r"<script>(.*?)</script>", HTML, re.S):
            self.assertLess(len(inline), 300)
            self.assertIn("answerarena.theme", inline)

    def test_clients_use_only_chain_and_account(self):
        calls = re.findall(r"createClient\(\{([^}]*)\}\)", SCRIPT)
        self.assertGreaterEqual(len(calls), 3)
        for body in calls:
            self.assertTrue(body.strip().startswith("chain: studionet"), body)
            self.assertNotIn("provider", body)

    def test_default_address_constant_and_query_override(self):
        self.assertRegex(HTML, r'DEFAULT_CONTRACT_ADDRESS = "0x[0-9a-fA-F]{40}"')
        self.assertIn('get("contract")', SCRIPT)

    def test_every_called_method_exists(self):
        called = set(re.findall(r'(?:read|readJson)\("([a-z_]+)"', SCRIPT))
        called |= set(re.findall(r'write\([^,]+,\s*[^,]+,\s*"([a-z_]+)"', SCRIPT))
        self.assertGreaterEqual(len(called), 14)
        self.assertEqual(called - methods(), set())

    def test_every_write_is_reachable(self):
        for name in ("post_question", "submit_answer", "cancel_question", "grade", "accept_result", "dispute",
                     "finalize", "void_question", "withdraw", "push_payment"):
            self.assertIn(f'"{name}"', SCRIPT)

    def test_every_view_the_page_needs_is_used(self):
        for name in ("get_config", "get_stats", "get_accounting", "get_activity", "list_questions", "get_question",
                     "get_answers", "get_asker_questions", "get_answerer_answers", "get_pending_withdrawal"):
            self.assertIn(f'"{name}"', SCRIPT)

    def test_argument_orders(self):
        self.assertEqual(params_of("post_question"), ["title", "details", "rubric", "min_score", "window_minutes"])
        self.assertIn('"post_question", [draft.title', SCRIPT)
        self.assertEqual(params_of("submit_answer"), ["question_id", "kind", "content"])
        self.assertIn('"submit_answer", [q.id, form.kind, form.text.trim()]', SCRIPT)
        self.assertEqual(params_of("dispute"), ["question_id", "reason"])
        self.assertIn('"dispute", [q.id, form.reason.trim()]', SCRIPT)
        self.assertEqual(params_of("list_questions"), ["offset", "limit", "status"])
        self.assertIn('"list_questions", [qf.items.length, 20, qf.status]', SCRIPT)

    def test_fields_read_from_json_exist_in_contract(self):
        for field in ("answer_fee_wei", "min_bounty_wei", "dispute_bond_bps", "min_dispute_bond_wei", "max_criteria",
                      "grade_timeout_seconds", "locked_matches_questions", "balance_covers_liabilities", "owed_total",
                      "locked_total", "criteria_scores", "first_score", "dispute_deadline_epoch", "has_more", "fetched"):
            self.assertIn(field, CONTRACT, field)
            self.assertIn(field, SCRIPT, field)

    def test_no_html_injection_paths(self):
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(forbidden, SCRIPT)

    def test_private_key_never_in_local_storage(self):
        self.assertNotRegex(SCRIPT, r"localStorage\.setItem\([^)]*(pk|key)", )

    def test_transaction_states_and_messages(self):
        for text in ("Waiting for your signature", "Submitted to the network", "Accepted by validators", "Finalized",
                     "You declined the request in your wallet", "Not enough GEN", "Your wallet is on another network",
                     "The contract refused this call", "was credited to your balance"):
            self.assertIn(text, SCRIPT)
        self.assertIn('status: "ACCEPTED"', SCRIPT)
        self.assertIn('status: "FINALIZED"', SCRIPT)
        self.assertGreaterEqual(SCRIPT.count("confirmAction({"), 5)

    def test_design_rules(self):
        self.assertIn("Public+Sans", HTML)
        self.assertIn("text-size-adjust:100%", HTML)
        self.assertIn("prefers-color-scheme:dark", HTML)
        self.assertNotIn("gradient(", HTML)
        self.assertNotIn("tabular-nums", HTML)
        self.assertNotRegex(HTML, r'type="date"')
        self.assertIn("@media (min-width:1024px)", HTML)
        self.assertIn("Live contract activity", SCRIPT)
        self.assertIn("Balanced", SCRIPT)

    def test_accessibility_basics(self):
        self.assertIn('<html lang="en">', HTML)
        self.assertIn("prefers-reduced-motion", HTML)
        self.assertIn(":focus-visible", HTML)
        self.assertIn("showModal()", HTML)

    def test_page_is_english_only(self):
        for ch in set(HTML):
            self.assertFalse("؀" <= ch <= "ۿ", "Persian/Arabic text found")


if __name__ == "__main__":
    unittest.main()
