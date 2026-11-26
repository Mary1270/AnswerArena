import json
import random
import unittest

from tests._support import (
    ALICE, ASKER, ASKER_2, BOB, CAROL, CLOCK, GEN, KEEPER, RUBRIC, SANDBOX, AnswerArena, Model, Rejected, Web,
    answer, as_caller, call, check_books, close, expect_error, finalize, fresh, gl, grade, m, pay, pending, post,
)


class TestPosting(unittest.TestCase):
    def setUp(self):
        self.c = fresh()

    def test_post_locks_bounty_and_logs(self):
        qid = post(self.c, bounty=12)
        q = call(self.c, "get_question", qid)
        self.assertEqual(q["status"], "OPEN")
        self.assertEqual(q["criteria"], ["Correct final answer", "Shows the reasoning", "Cites a source"])
        self.assertEqual(q["pot"], str(12 * GEN))
        self.assertEqual(q["deadline_epoch"] - q["created_epoch"], 3600)
        events = call(self.c, "get_activity", 0, 10)["items"]
        self.assertEqual(events[0]["kind"], "POSTED")
        self.assertEqual(events[0]["title"], q["title"])
        check_books(self, self.c)

    def test_rubric_limits(self):
        as_caller(ASKER)
        for bad in ("", "a|b", "one|two|three|four|five", "x" * 161):
            with self.assertRaises(Rejected):
                pay(self.c, "post_question", 5 * GEN, "A valid question title", "", bad, 50, 60)
        qid = post(self.c, rubric="Accuracy\nClarity | Brevity")
        self.assertEqual(len(call(self.c, "get_question", qid)["criteria"]), 3)
        check_books(self, self.c)

    def test_bounds_bounce_with_refund(self):
        as_caller(ASKER)
        cases = [
            (0, "A valid question title", 50, 60),
            (5 * GEN, "short", 50, 60),
            (5 * GEN, "A valid question title", 5, 60),
            (5 * GEN, "A valid question title", 95, 60),
            (5 * GEN, "A valid question title", 50, 99999999),
        ]
        for value, title, score, minutes in cases:
            if value == 0:
                with self.assertRaises(gl.vm.UserError):
                    self.c.post_question(title, "", RUBRIC, score, minutes)
                continue
            with self.assertRaises(Rejected):
                pay(self.c, "post_question", value, title, "", RUBRIC, score, minutes)
        self.assertEqual(pending(self.c, ASKER), 4 * 5 * GEN)
        self.assertEqual(call(self.c, "get_stats")["questions"], 0)
        check_books(self, self.c)

    def test_window_minimum_depends_on_build(self):
        as_caller(ASKER)
        if SANDBOX:
            qid = pay(self.c, "post_question", 2 * GEN, "A valid question title", "", RUBRIC, 50, 1)["question_id"]
            self.assertTrue(qid)
        else:
            with self.assertRaises(Rejected):
                pay(self.c, "post_question", 2 * GEN, "A valid question title", "", RUBRIC, 50, 1)

    def test_cancel_only_without_answers(self):
        qid = post(self.c)
        as_caller(ALICE)
        expect_error(self, self.c.cancel_question, qid)
        as_caller(ASKER)
        call(self.c, "cancel_question", qid)
        self.assertEqual(pending(self.c, ASKER), 10 * GEN)
        self.assertEqual(call(self.c, "get_question", qid)["status"], "CANCELLED")
        qid2 = post(self.c)
        answer(self.c, qid2, ALICE)
        as_caller(ASKER)
        self.assertIn("answers", expect_error(self, self.c.cancel_question, qid2))
        check_books(self, self.c)


class TestAnswering(unittest.TestCase):
    def setUp(self):
        self.c = fresh()
        self.q = post(self.c)

    def test_fee_adds_to_pot_and_overpay_is_credited(self):
        out = answer(self.c, self.q, ALICE, fee=3)
        self.assertEqual(out["refunded_wei"], str(2 * GEN))
        self.assertEqual(pending(self.c, ALICE), 2 * GEN)
        q = call(self.c, "get_question", self.q)
        self.assertEqual(q["pot"], str(11 * GEN))
        self.assertEqual(q["answer_count"], 1)
        check_books(self, self.c)

    def test_rules(self):
        as_caller(ASKER)
        with self.assertRaises(Rejected):
            pay(self.c, "submit_answer", GEN, self.q, "TEXT", "my own answer")
        answer(self.c, self.q, ALICE)
        with self.assertRaises(Rejected):
            answer(self.c, self.q, ALICE)
        with self.assertRaises(Rejected):
            as_caller(BOB)
            pay(self.c, "submit_answer", GEN // 2, self.q, "TEXT", "x y z")
        with self.assertRaises(Rejected):
            answer(self.c, self.q, BOB, content="http://not-secure.example.com/page", kind="URL")
        with self.assertRaises(Rejected):
            answer(self.c, self.q, BOB, content="hello", kind="IMAGE")
        answer(self.c, self.q, BOB, content="https://example.org/boiling-point", kind="url")
        close(self.c, self.q)
        with self.assertRaises(Rejected):
            answer(self.c, self.q, CAROL)
        items = call(self.c, "get_answers", self.q)["items"]
        self.assertEqual([a["kind"] for a in items], ["TEXT", "URL"])
        check_books(self, self.c)

    def test_answer_cap(self):
        for i in range(AnswerArena.MAX_ANSWERS):
            answer(self.c, self.q, "0x" + f"{i + 16:02x}" * 20)
        with self.assertRaises(Rejected):
            answer(self.c, self.q, CAROL)
        check_books(self, self.c)


class TestGrading(unittest.TestCase):
    def setUp(self):
        self.c = fresh()
        self.q = post(self.c, bounty=10)
        answer(self.c, self.q, ALICE, content="Roughly 93 C.")
        answer(self.c, self.q, BOB, content="https://example.org/altitude", kind="URL")
        answer(self.c, self.q, CAROL, content="100 C, always.")
        self.web = Web({"https://example.org/altitude": "At 2000 m water boils near 93.4 C (source: tables)."})

    def test_not_before_deadline(self):
        as_caller(KEEPER)
        self.assertIn("still open", expect_error(self, self.c.grade, self.q))

    def test_best_answer_wins_after_window(self):
        close(self.c, self.q)
        model = Model({"a0": [8, 6, 2], "a1": [9, 8, 9], "a2": [1, 1, 0]})
        out = grade(self.c, self.q, model, self.web)
        self.assertEqual(out["winner"], 1)
        self.assertEqual(out["scores"], [53, 87, 7])
        self.assertIn("93.4 C", model.prompts[0])
        self.assertIn("untrusted", model.prompts[0])
        q = call(self.c, "get_question", self.q)
        self.assertEqual(q["status"], "GRADED")
        self.assertEqual(q["dispute_bond"], str(2 * GEN))
        items = call(self.c, "get_answers", self.q)["items"]
        self.assertEqual([a["rank"] for a in items], [2, 1, 3])
        self.assertEqual(items[1]["criteria_scores"], [9, 8, 9])
        CLOCK.advance(AnswerArena.DISPUTE_WINDOW_SECONDS - 1)
        as_caller(KEEPER)
        self.assertIn("dispute window", expect_error(self, self.c.finalize, self.q))
        CLOCK.advance(1)
        finalize(self.c, self.q)
        self.assertEqual(pending(self.c, BOB), 13 * GEN)
        as_caller(BOB)
        self.c.withdraw()
        self.assertEqual(gl.evm.transfers[-1], {"to": BOB, "value": 13 * GEN})
        check_books(self, self.c)

    def test_tie_goes_to_earliest(self):
        close(self.c, self.q)
        out = grade(self.c, self.q, Model({"a0": [7, 7, 7], "a1": [7, 7, 7], "a2": [7, 7, 7]}), self.web)
        self.assertEqual(out["winner"], 0)

    def test_no_pass_refunds_pot_to_asker(self):
        close(self.c, self.q)
        out = grade(self.c, self.q, Model({"a0": [3, 3, 3], "a1": [4, 4, 4], "a2": [1, 0, 0]}), self.web)
        self.assertEqual(out["outcome"], "REFUNDED")
        q = call(self.c, "get_question", self.q)
        self.assertEqual((q["status"], q["outcome"]), ("SETTLED", "REFUNDED"))
        self.assertEqual(pending(self.c, ASKER), 13 * GEN)
        check_books(self, self.c)

    def test_no_answers_refunds_without_model(self):
        q2 = post(self.c, who=ASKER_2, bounty=4)
        close(self.c, q2)
        model = Model()
        out = grade(self.c, q2, model)
        self.assertEqual(out["outcome"], "REFUNDED")
        self.assertEqual(model.prompts, [])
        self.assertEqual(pending(self.c, ASKER_2), 4 * GEN)
        check_books(self, self.c)

    def test_unreachable_link_is_flagged_and_scored_zero_by_prompt(self):
        close(self.c, self.q)
        model = Model({"a0": [8, 8, 8], "a1": [0, 0, 0], "a2": [1, 1, 1]})
        grade(self.c, self.q, model, Web())
        self.assertIn("could not be fetched", model.prompts[0])
        items = call(self.c, "get_answers", self.q)["items"]
        self.assertFalse(items[1]["fetched"])

    def test_model_failures_record_nothing(self):
        close(self.c, self.q)
        for model in (Model(fail=True), Model(raw="not json"), Model(raw={"scores": [{"id": "a0", "criteria": [1]}]}),
                      Model(raw={"scores": [{"id": "a0", "criteria": [1, 2, 3]}]})):
            as_caller(KEEPER)
            msg = expect_error(self, grade, self.c, self.q, model, self.web)
            self.assertIn("Nothing was recorded", msg)
        self.assertEqual(call(self.c, "get_question", self.q)["status"], "OPEN")

    def test_messy_model_output_is_normalized(self):
        close(self.c, self.q)
        raw = '```json\n{"scores": [{"id": "A0", "criteria": ["7", 7.6, 12], "note": "ok"}, ' \
              '{"id": "a1", "criteria": [-3, 9.5, 9]}, {"id": "a2", "criteria": [0, 0, 0]}, ' \
              '{"id": "a9", "criteria": [10, 10, 10]}]}\n```'
        out = grade(self.c, self.q, Model(raw=raw), self.web)
        items = call(self.c, "get_answers", self.q)["items"]
        self.assertEqual(items[0]["criteria_scores"], [7, 8, 10])
        self.assertEqual(items[1]["criteria_scores"], [0, 10, 9])
        self.assertEqual(out["winner"], 0)

    def test_void_after_grading_timeout_refunds_everyone(self):
        close(self.c, self.q)
        as_caller(KEEPER)
        expect_error(self, self.c.void_question, self.q)
        CLOCK.advance(AnswerArena.GRADE_TIMEOUT_SECONDS)
        call(self.c, "void_question", self.q)
        self.assertEqual(pending(self.c, ASKER), 10 * GEN)
        for who in (ALICE, BOB, CAROL):
            self.assertEqual(pending(self.c, who), GEN)
        check_books(self, self.c)


class TestValidator(unittest.TestCase):
    CTX = {"title": "t", "details": "", "criteria": ["a", "b"], "min_score": 50,
           "answers": [{"kind": "TEXT", "content": "x"}, {"kind": "TEXT", "content": "y"}]}

    def sheet(self, rows, ok=True):
        return {"ok": ok, "error": "", "scores": rows, "notes": ["n"] * len(rows), "fetched": [True] * len(rows)}

    def test_agree_on_close_scores_and_same_pick(self):
        self.assertTrue(m._grade_agree(self.sheet([[8, 8], [4, 4]]), self.sheet([[7, 9], [5, 5]]), self.CTX))

    def test_reject_far_scores(self):
        self.assertFalse(m._grade_agree(self.sheet([[10, 10], [0, 0]]), self.sheet([[5, 5], [6, 6]]), self.CTX))

    def test_close_race_is_accepted_within_margin(self):
        self.assertTrue(m._grade_agree(self.sheet([[8, 8], [7, 8]]), self.sheet([[7, 8], [8, 8]]), self.CTX))

    def test_reject_clearly_worse_pick(self):
        self.assertFalse(m._grade_agree(self.sheet([[8, 8], [6, 6]]), self.sheet([[6, 6], [9, 9]]), self.CTX))

    def test_no_winner_needs_validator_near_threshold(self):
        self.assertTrue(m._grade_agree(self.sheet([[4, 4], [3, 3]]), self.sheet([[5, 5], [3, 3]]), self.CTX))
        self.assertFalse(m._grade_agree(self.sheet([[4, 4], [3, 3]]), self.sheet([[7, 7], [3, 3]]), self.CTX))

    def test_shape_and_failure(self):
        self.assertFalse(m._grade_agree(self.sheet([[8, 8]]), self.sheet([[8, 8], [1, 1]]), self.CTX))
        self.assertFalse(m._grade_agree(self.sheet([[8, 11], [1, 1]]), self.sheet([[8, 8], [1, 1]]), self.CTX))
        self.assertFalse(m._grade_agree(self.sheet([[8, True], [1, 1]]), self.sheet([[8, 8], [1, 1]]), self.CTX))
        self.assertTrue(m._grade_agree(self.sheet([], ok=False), self.sheet([], ok=False), self.CTX))
        self.assertFalse(m._grade_agree(self.sheet([], ok=False), self.sheet([[8, 8], [1, 1]]), self.CTX))
        self.assertFalse(m._grade_agree("junk", self.sheet([[8, 8], [1, 1]]), self.CTX))

    def test_validator_rejection_records_nothing(self):
        c = fresh()
        q = post(c)
        answer(c, q, ALICE)
        close(c, q)

        def hook(result, validator):
            if not validator(gl.vm.Return(dict(result, scores=[[10, 10, 10]]))):
                raise gl.vm.UserError("validators rejected the leader result")
        gl.vm.validator_hook = hook
        expect_error(self, grade, c, q, Model({"a0": [2, 2, 2]}))
        self.assertEqual(call(c, "get_question", q)["status"], "OPEN")
        gl.vm.validator_hook = None


class TestDisputes(unittest.TestCase):
    def setUp(self):
        self.c = fresh()
        self.q = post(self.c, bounty=20)
        answer(self.c, self.q, ALICE, content="Answer one")
        answer(self.c, self.q, BOB, content="Answer two")
        close(self.c, self.q)
        grade(self.c, self.q, Model({"a0": [9, 9, 9], "a1": [6, 6, 6]}))

    def dispute(self, who=ASKER, bond=3, reason="Answer two is the only one that cites a real source."):
        as_caller(who)
        return pay(self.c, "dispute", bond * GEN, self.q, reason)

    def test_only_asker_once_within_window_with_bond(self):
        with self.assertRaises(Rejected):
            self.dispute(who=ALICE)
        with self.assertRaises(Rejected):
            self.dispute(bond=2)
        with self.assertRaises(Rejected):
            self.dispute(reason="short")
        out = self.dispute(bond=4)
        self.assertEqual(out["refunded_wei"], str(GEN))
        with self.assertRaises(Rejected):
            self.dispute()
        self.assertEqual(call(self.c, "get_question", self.q)["status"], "DISPUTED")
        check_books(self, self.c)

    def test_closed_window(self):
        CLOCK.advance(AnswerArena.DISPUTE_WINDOW_SECONDS)
        with self.assertRaises(Rejected):
            self.dispute()

    def test_rejected_dispute_pays_bond_to_winner(self):
        self.dispute()
        model = Model({"a0": [9, 8, 9], "a1": [6, 7, 6]})
        out = finalize(self.c, self.q, model)
        self.assertFalse(out["dispute_upheld"])
        self.assertIn("disputed an earlier grading", model.prompts[0])
        self.assertIn("cites a real source", model.prompts[0])
        self.assertEqual(pending(self.c, ALICE), (22 + 3) * GEN)
        items = call(self.c, "get_answers", self.q)["items"]
        self.assertEqual(items[0]["first_score"], 90)
        check_books(self, self.c)

    def test_upheld_dispute_changes_winner_and_returns_bond(self):
        self.dispute()
        out = finalize(self.c, self.q, Model({"a0": [5, 5, 5], "a1": [8, 9, 9]}))
        self.assertTrue(out["dispute_upheld"])
        self.assertEqual(out["winner"], 1)
        self.assertEqual(pending(self.c, BOB), 22 * GEN)
        self.assertEqual(pending(self.c, ASKER), 3 * GEN)
        self.assertEqual(call(self.c, "get_stats")["disputes_upheld"], 1)
        check_books(self, self.c)

    def test_upheld_dispute_to_no_winner_refunds(self):
        self.dispute()
        out = finalize(self.c, self.q, Model({"a0": [3, 3, 3], "a1": [2, 2, 2]}))
        self.assertEqual(out["outcome"], "REFUNDED")
        self.assertEqual(pending(self.c, ASKER), (22 + 3) * GEN)
        check_books(self, self.c)

    def test_accept_early(self):
        as_caller(ALICE)
        expect_error(self, self.c.accept_result, self.q)
        as_caller(ASKER)
        call(self.c, "accept_result", self.q)
        self.assertEqual(pending(self.c, ALICE), 22 * GEN)
        with self.assertRaises(Rejected):
            self.dispute()
        check_books(self, self.c)

    def test_stale_dispute_lapses_to_original_result(self):
        self.dispute()
        as_caller(KEEPER)
        expect_error(self, self.c.void_question, self.q)
        CLOCK.advance(AnswerArena.GRADE_TIMEOUT_SECONDS)
        call(self.c, "void_question", self.q)
        self.assertEqual(pending(self.c, ALICE), 22 * GEN)
        self.assertEqual(pending(self.c, ASKER), 3 * GEN)
        check_books(self, self.c)


class TestViews(unittest.TestCase):
    def test_lists_indexes_and_stats(self):
        c = fresh()
        q0 = post(c, bounty=5)
        q1 = post(c, who=ASKER_2, bounty=7)
        answer(c, q0, ALICE)
        answer(c, q1, ALICE)
        page = call(c, "list_questions", 0, 1)
        self.assertEqual(page["items"][0]["id"], q1)
        self.assertTrue(page["has_more"])
        self.assertEqual(call(c, "list_questions", 0, 10, "open")["total"], 2)
        self.assertEqual(call(c, "get_asker_questions", ASKER.upper().replace("0X", "0x"))["items"][0]["id"], q0)
        mine = call(c, "get_answerer_answers", ALICE)["items"]
        self.assertEqual([a["question"]["id"] for a in mine], [q1, q0])
        stats = call(c, "get_stats")
        self.assertEqual((stats["questions"], stats["answers"], stats["open"]), (2, 2, 2))
        self.assertEqual(stats["locked_total"], str(14 * GEN))
        cfg = call(c, "get_config")
        self.assertEqual(cfg["answer_fee_wei"], str(GEN))
        self.assertEqual(cfg["max_criteria"], 4)
        feed = call(c, "get_activity", 0, 3)
        self.assertEqual(feed["total"], 4)
        self.assertEqual([e["kind"] for e in feed["items"]], ["ANSWERED", "ANSWERED", "POSTED"])
        self.assertTrue(all(isinstance(e["epoch"], int) for e in feed["items"]))

    def test_unknown_question(self):
        c = fresh()
        expect_error(self, c.get_question, "q_9")


class TestFuzzAccounting(unittest.TestCase):
    def test_random_lifecycles_keep_books_balanced(self):
        rng = random.Random(7)
        c = fresh()
        people = ["0x" + f"{i:02x}" * 20 for i in range(32, 40)]
        for round_ in range(25):
            asker = rng.choice(people)
            qid = post(c, who=asker, bounty=rng.randint(1, 30), min_score=rng.choice([30, 50, 70]))
            for who in rng.sample([p for p in people if p != asker], rng.randint(0, 4)):
                answer(c, qid, who, fee=rng.randint(1, 2))
            close(c, qid)
            q = call(c, "get_question", qid)
            if q["answer_count"] == 0 and rng.random() < 0.3:
                as_caller(asker)
                call(c, "cancel_question", qid)
                continue
            marks = {f"a{i}": [rng.randint(0, 10) for _ in range(3)] for i in range(q["answer_count"])}
            if rng.random() < 0.15:
                CLOCK.advance(AnswerArena.GRADE_TIMEOUT_SECONDS)
                as_caller(KEEPER)
                call(c, "void_question", qid)
            else:
                grade(c, qid, Model(marks))
                q = call(c, "get_question", qid)
                if q["status"] == "GRADED":
                    roll = rng.random()
                    if roll < 0.4:
                        as_caller(asker)
                        pay(c, "dispute", int(q["dispute_bond"]), qid, "I think the grading missed the rubric.")
                        remarks = {k: [rng.randint(0, 10) for _ in range(3)] for k in marks}
                        finalize(c, qid, Model(remarks))
                    elif roll < 0.7:
                        as_caller(asker)
                        call(c, "accept_result", qid)
                    else:
                        CLOCK.advance(AnswerArena.DISPUTE_WINDOW_SECONDS)
                        finalize(c, qid)
            check_books(self, c)
            if rng.random() < 0.5:
                who = rng.choice(people)
                if pending(c, who):
                    as_caller(KEEPER)
                    c.push_payment(who)
                    check_books(self, c)
        acct = check_books(self, c)
        self.assertEqual(int(acct["locked_total"]), 0)


if __name__ == "__main__":
    unittest.main()
