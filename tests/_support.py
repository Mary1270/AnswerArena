"""
Test bootstrap: loads the contract (contract.py, or the file in AA_CONTRACT)
against the offline SDK stub, replaces the clock with a controllable one, and
provides helpers for payable calls, mocked web pages and a scripted model.
"""
import datetime as _dt
import importlib.util
import json
import os
import re
import sys
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_STUB = os.path.join(_HERE, "genlayer_stub")
if _STUB not in sys.path:
    sys.path.insert(0, _STUB)

ROOT = os.path.dirname(_HERE)
CONTRACT_PATH = os.environ.get("AA_CONTRACT") or os.path.join(ROOT, "contract.py")
_spec = importlib.util.spec_from_file_location("answerarena_contract", CONTRACT_PATH)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

AnswerArena = m.AnswerArena
gl = m.gl
Address = m.Address
GEN = 10 ** 18
SANDBOX = AnswerArena.MODE == "sandbox"
UTC = _dt.timezone.utc
BASE = _dt.datetime(2026, 11, 1, 9, 0, 0, tzinfo=UTC)

ASKER = "0x" + "a1" * 20
ASKER_2 = "0x" + "a2" * 20
ALICE = "0x" + "b1" * 20
BOB = "0x" + "b2" * 20
CAROL = "0x" + "b3" * 20
KEEPER = "0x" + "c1" * 20
RUBRIC = "Correct final answer | Shows the reasoning | Cites a source"


class Clock:
    def __init__(self):
        self.now = BASE

    def advance(self, seconds):
        self.now = self.now + _dt.timedelta(seconds=seconds)


CLOCK = Clock()
AnswerArena._now_utc = staticmethod(lambda: CLOCK.now)
_FLOW = {"in": 0}


class Rejected(Exception):
    pass


def as_caller(address):
    gl.message.sender_address = Address(address)


def fresh():
    CLOCK.now = BASE
    gl.evm.transfers.clear()
    gl.vm.validator_hook = None
    _FLOW["in"] = 0
    as_caller(ASKER)
    return AnswerArena()


def pay(contract, method, value, *args):
    """Call a payable method with `value` wei attached. A bounced call must
    credit exactly `value` back and is raised as Rejected."""
    gl.message.value = m.u256(value)
    contract.balance = m.u256(int(contract.balance) + value)
    _FLOW["in"] += value
    try:
        out = getattr(contract, method)(*args)
    except Exception:
        contract.balance = m.u256(int(contract.balance) - value)
        _FLOW["in"] -= value
        raise
    finally:
        gl.message.value = m.u256(0)
    data = json.loads(out)
    if "rejected" in data:
        assert data["refunded_wei"] == str(value), data
        raise Rejected(data["rejected"])
    return data


def sync_balance(contract):
    out = sum(t["value"] for t in gl.evm.transfers)
    contract.balance = m.u256(_FLOW["in"] - out)


def call(contract, method, *args):
    return json.loads(getattr(contract, method)(*args))


class Model:
    """Scripted grader: `marks` maps answer tag (a0, a1, ...) to its list of
    criterion scores; `raw` overrides the whole reply."""

    def __init__(self, marks=None, raw=None, fail=False):
        self.marks = marks or {}
        self.raw = raw
        self.fail = fail
        self.prompts = []

    def __call__(self, prompt, response_format="text"):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("model offline")
        if self.raw is not None:
            return self.raw
        tags = re.findall(r'<answer id="(a[0-9]+)">', prompt)
        count = len(re.findall(r"^[0-9]+\. ", prompt, re.M))
        return {"scores": [{"id": tag, "criteria": self.marks.get(tag, [5] * count), "note": f"note for {tag}"}
                           for tag in tags]}


class Web:
    def __init__(self, pages=None):
        self.pages = pages or {}
        self.calls = []

    def render(self, url, mode="text"):
        self.calls.append(url)
        if url in self.pages:
            body = self.pages[url]
            if isinstance(body, Exception):
                raise body
            return body
        raise RuntimeError("404")


def run_with(model, web=None):
    web = web or Web()
    return patch.object(gl.nondet, "exec_prompt", side_effect=model), patch.object(
        gl.nondet.web, "render", side_effect=web.render)


def post(contract, who=ASKER, bounty=10, title="What is the boiling point of water at 2000 m?",
         details="Give the temperature in Celsius.", rubric=RUBRIC, min_score=50, minutes=60):
    as_caller(who)
    return pay(contract, "post_question", bounty * GEN, title, details, rubric, min_score, minutes)["question_id"]


def answer(contract, qid, who, content="About 93 C because pressure falls with altitude.", kind="TEXT", fee=1):
    as_caller(who)
    return pay(contract, "submit_answer", fee * GEN, qid, kind, content)


def close(contract, qid):
    q = call(contract, "get_question", qid)
    CLOCK.now = _dt.datetime.fromtimestamp(int(q["deadline_epoch"]), UTC)


def grade(contract, qid, model, web=None, who=KEEPER):
    as_caller(who)
    p1, p2 = run_with(model, web)
    with p1, p2:
        return call(contract, "grade", qid)


def finalize(contract, qid, model=None, web=None, who=KEEPER):
    as_caller(who)
    p1, p2 = run_with(model or Model(), web)
    with p1, p2:
        return call(contract, "finalize", qid)


def pending(contract, address):
    return int(contract.get_pending_withdrawal(address))


def expect_error(testcase, fn, *args):
    with testcase.assertRaises(gl.vm.UserError) as ctx:
        fn(*args)
    return str(ctx.exception)


def check_books(testcase, contract):
    sync_balance(contract)
    acct = json.loads(contract.get_accounting())
    testcase.assertTrue(acct["balance_covers_liabilities"], acct)
    testcase.assertTrue(acct["locked_matches_questions"], acct)
    testcase.assertEqual(int(acct["contract_balance"]), int(acct["liabilities"]), acct)
    testcase.assertEqual(sum(int(v) for v in contract.pending_withdrawals.values()), int(contract.owed_total))
    stats = json.loads(contract.get_stats())
    testcase.assertEqual(sum(stats[s.lower()] for s in m.STATUSES), stats["questions"])
    return acct
