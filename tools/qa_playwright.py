#!/usr/bin/env python3
"""
Browser QA for index.html. Not part of the offline unit tests: it needs
Playwright and a Chromium/Chrome binary (set CHROME_PATH if it is not the
Playwright default).

It runs the real contract (from the offline SDK stub) behind the page: the
genlayer-js module and the Studio RPC are replaced by small stubs that call
into Python, so every view shows real contract state and every transaction
goes through the real contract code.

Usage (from the repository root):
    AA_CONTRACT=$PWD/contract_sandbox.py python3 tools/qa_playwright.py [--shots DIR]

Checks: widths 320 to 1440 in both themes, no horizontal overflow, touch
targets of at least 36 px, no page-wide tabular-nums, text-size-adjust, no
console errors, plus an end-to-end run of both lab scenarios.
"""
import datetime as dt
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("AA_CONTRACT", os.path.join(ROOT, "contract_sandbox.py"))

from playwright.sync_api import sync_playwright  # noqa: E402

from tests import _support as T  # noqa: E402

m, gl, GEN = T.m, T.gl, T.GEN
m.AnswerArena.DISPUTE_WINDOW_SECONDS = 6 * 3600
SKEW = {"s": 0}


def real_now():
    return dt.datetime.now(dt.timezone.utc)


def set_clock(delta_seconds=0):
    T.CLOCK.now = real_now() + dt.timedelta(seconds=delta_seconds + SKEW["s"])


def smart_model(prompt, response_format="text"):
    import re
    count = len(re.findall(r"^[0-9]+\. ", prompt, re.M))
    out = []
    for tag, body in re.findall(r'<answer id="(a[0-9]+)">\n(.*?)\n</answer>', prompt, re.S):
        low = body.lower()
        good = "tidal" in low or "canberra" in low or "pressure" in low or len(body) > 120
        out.append({"id": tag, "criteria": [9] * count if good else [1] * count, "note": "Scored against the rubric."})
    return {"scores": out}


C = {"c": None}


def seed():
    c = T.fresh()
    C["c"] = c
    A, A2, AL, BO, CA = T.ASKER, T.ASKER_2, T.ALICE, T.BOB, T.CAROL

    def post(who, bounty, title, minutes, at):
        T.CLOCK.now = real_now() + dt.timedelta(seconds=at)
        return T.post(c, who=who, bounty=bounty, title=title, minutes=minutes, min_score=50,
                      details="Be concrete and keep it short.", rubric="Correct answer | Shows the reasoning | Cites a source")

    def ans(qid, who, text, at, kind="TEXT"):
        T.CLOCK.now = real_now() + dt.timedelta(seconds=at)
        T.answer(c, qid, who, text, kind=kind)

    def grade(qid, at):
        T.CLOCK.now = real_now() + dt.timedelta(seconds=at)
        T.as_caller(T.KEEPER)
        p1, p2 = T.run_with(smart_model, T.Web({"https://example.org/boiling": "At 2000 m water boils near 93 C because pressure is lower."}))
        with p1, p2:
            c.grade(qid)

    q0 = post(A, 12, "How do I read a candlestick chart without prior experience?", 60, -6 * 3600)
    ans(q0, AL, "Each candle shows open, high, low and close for one period. The body is the open to close range; wicks show extremes, and green or red shows direction. Because it compresses four numbers into one shape, patterns appear.", -5.5 * 3600)
    ans(q0, BO, "Candles are just colored bars.", -5.4 * 3600)
    grade(q0, -4.9 * 3600)
    T.CLOCK.now = real_now() + dt.timedelta(seconds=-4.5 * 3600)
    T.as_caller(A)
    c.accept_result(q0)

    q1 = post(A2, 8, "What is the boiling point of water at 2000 m altitude?", 180, -20 * 60)
    ans(q1, AL, "About 93 C, because air pressure falls with altitude.", -12 * 60)
    ans(q1, BO, "https://example.org/boiling", -10 * 60, kind="URL")

    q2 = post(A, 20, "Why does the Moon always show the same face to Earth?", 60, -3 * 3600)
    ans(q2, AL, "Tidal locking: Earth's gravity slowed the Moon's spin until rotation matched its orbit.", -2.9 * 3600)
    ans(q2, CA, "Because it is stuck.", -2.8 * 3600)
    grade(q2, -60)

    q3 = post(A2, 6, "Which is the capital of Australia?", 60, -5 * 3600)
    ans(q3, CA, "I like pizza.", -4.9 * 3600)
    grade(q3, -3.5 * 3600)

    q4 = post(A, 9, "What is the best way to learn touch typing in a month?", 60, -3 * 3600)
    ans(q4, BO, "Practice ten minutes daily with a home-row drill and never look down.", -2.5 * 3600)

    q5 = post(A2, 15, "Explain why the sky is blue in two sentences.", 60, -3 * 3600)
    ans(q5, AL, "Shorter blue wavelengths scatter more strongly in air, a tidal-free effect called Rayleigh scattering.", -2.9 * 3600)
    ans(q5, CA, "Because of the sea.", -2.8 * 3600)
    grade(q5, -300)
    T.CLOCK.now = real_now() + dt.timedelta(seconds=-120)
    T.as_caller(A2)
    T.pay(c, "dispute", int(json.loads(c.get_question(q5))["dispute_bond"]), q5, "The first answer names the right effect but the grading ignored the second criterion.")

    q6 = post(A, 3, "Is a tomato a fruit or a vegetable? Answer with reasons.", 60, -2 * 3600)
    T.as_caller(A)
    T.CLOCK.now = real_now() + dt.timedelta(seconds=-1.9 * 3600)
    c.cancel_question(q6)
    set_clock()
    T.check_books(__import__("unittest").TestCase(), c)
    return c


BAL = {}


def handle_call(kind, fn, args, value, sender):
    c = C["c"]
    set_clock()
    method = getattr(c, fn)
    try:
        if kind == "read":
            return {"ok": True, "out": method(*args)}
        T.as_caller(sender)
        value = int(value or 0)
        gl.message.value = m.u256(value)
        c.balance = m.u256(int(c.balance) + value)
        T._FLOW["in"] += value
        p1, p2 = T.run_with(smart_model, T.Web())
        try:
            with p1, p2:
                out = method(*args)
            BAL[sender.lower()] = BAL.get(sender.lower(), 0) - value
            return {"ok": True, "out": out}
        except gl.vm.UserError as e:
            c.balance = m.u256(int(c.balance) - value)
            T._FLOW["in"] -= value
            return {"ok": False, "out": str(e)}
        finally:
            gl.message.value = m.u256(0)
    except Exception as e:
        return {"ok": False, "out": f"{type(e).__name__}: {e}"}


STUB_GL = """
const pending = new Map();
let n = 0;
export function createAccount(pk) { return { address: "0x" + String(pk).slice(-40), privateKey: pk }; }
export function createClient(opts) {
  const acct = opts && opts.account; const sender = acct ? (typeof acct === "string" ? acct : acct.address) : null;
  return {
    async readContract({ functionName, args }) {
      const r = await window.__call("read", functionName, args.map((a) => (typeof a === "bigint" ? a.toString() : a)), "0", sender || "");
      if (!r.ok) throw new Error(r.out);
      return r.out;
    },
    async writeContract({ functionName, args, value }) {
      const r = await window.__call("write", functionName, args.map((a) => (typeof a === "bigint" ? a.toString() : a)), String(value || 0n), sender);
      const hash = "0x" + (++n).toString(16).padStart(64, "0"); pending.set(hash, r); return hash;
    },
    async waitForTransactionReceipt({ hash, status }) {
      await new Promise((r) => setTimeout(r, status === "FINALIZED" ? 600 : 250));
      const r = pending.get(hash);
      return { consensus_data: { leader_receipt: [{ execution_result: r.ok ? "SUCCESS" : "ERROR", result: { payload: { readable: r.out } } }] } };
    },
  };
}
"""
STUB_CHAINS = 'export const studionet = { id: 61999, name: "Studio QA", nativeCurrency: { name: "GEN", symbol: "GEN", decimals: 18 }, rpcUrls: { default: { http: ["https://rpc.qa.test/api"] } } };'
INIT = """
window.__skewMs = 0; const _now = Date.now.bind(Date); Date.now = () => _now() + window.__skewMs;
"""


def install(page):
    page.add_init_script(INIT)
    page.route("https://esm.sh/genlayer-js@latest/chains", lambda r: r.fulfill(status=200, content_type="text/javascript", body=STUB_CHAINS))
    page.route("https://esm.sh/genlayer-js@latest", lambda r: r.fulfill(status=200, content_type="text/javascript", body=STUB_GL))
    page.route("https://fonts.googleapis.com/**", lambda r: r.abort())
    page.route("https://fonts.gstatic.com/**", lambda r: r.abort())

    def rpc(route):
        body = route.request.post_data_json
        method, params = body["method"], body["params"]
        if method == "eth_getBalance":
            res = hex(BAL.get(params[0].lower(), 0))
        elif method == "sim_fundAccount":
            BAL[params[0].lower()] = BAL.get(params[0].lower(), 0) + 100 * GEN
            res = None
        else:
            res = None
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"jsonrpc": "2.0", "id": 1, "result": res}))
    page.route("https://rpc.qa.test/**", rpc)


MEASURE = """() => {
  const vw = document.documentElement.clientWidth;
  const bad = [];
  const sel = 'a, button, input:not([type=hidden]), select, textarea, summary';
  for (const el of document.querySelectorAll(sel)) {
    if (el.classList.contains('skip')) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const r = el.getBoundingClientRect(); if (r.width === 0 || r.height === 0) continue;
    if (el.closest('dialog:not([open])')) continue;
    if (r.height < 35.5 || r.width < 35.5) bad.push((el.tagName + '.' + el.className + ' ' + (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 30) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)));
  }
  const overflow = document.documentElement.scrollWidth - vw;
  const wide = [...document.querySelectorAll('body *')].filter((e) => { const r = e.getBoundingClientRect(); return r.right > vw + 1 && r.width > 0 && !e.closest('.skip,.toasts,dialog') && getComputedStyle(e).position !== 'fixed'; }).slice(0, 5).map((e) => e.tagName + '.' + e.className);
  return { overflow, small: bad, wide, tnum: getComputedStyle(document.body).fontVariantNumeric, adjust: getComputedStyle(document.documentElement).webkitTextSizeAdjust || getComputedStyle(document.documentElement).textSizeAdjust };
}"""

WIDTHS = [320, 360, 390, 480, 720, 1024, 1440]
ROUTES = ["#/", "#/ask", "#/questions", "#/q/q_0", "#/q/q_1", "#/q/q_2", "#/q/q_3", "#/q/q_4", "#/q/q_5", "#/q/q_6", "#/mine", "#/lab"]
KEY_ASKER = "0x" + "00" * 12 + "a1" * 20


PITFALLS = r"""() => {
  const out = [];
  const vh = window.innerHeight, phone = window.innerWidth < 720;
  const lh = (el) => parseFloat(getComputedStyle(el).lineHeight);
  const lede = document.querySelector(".hero .lede");
  if (lede && Math.round(lede.getBoundingClientRect().height / lh(lede)) > 2) out.push("1 lede is longer than two lines");
  const tabs = document.querySelectorAll("nav.tabs ul li").length;
  if (tabs > 4) out.push("7 " + tabs + " tabs");
  const how = document.querySelector("details.how");
  if (how && phone && how.open) out.push("8 how-it-works open on phone");
  const mn = getComputedStyle(document.querySelector("main")).minHeight;
  if (mn !== "0px" && mn !== "auto" && mn !== "normal") out.push("11 main min-height " + mn);
  const fa = document.getElementById("footAddr").textContent;
  if (fa.length > 14 || document.getElementById("footCopy").hidden || document.getElementById("footExp").hidden) out.push("12 footer address not short with copy and explorer: " + fa);
  document.querySelectorAll(".qcard").forEach((c) => {
    const kids = [...c.children].map((e) => e.tagName + "." + e.className.split(" ")[0]);
    if (kids[0] !== "H3." || !kids[1].startsWith("SPAN.badge") || !kids[2].startsWith("P.amt") || !kids[4].startsWith("SPAN.btn")) out.push("5 card order " + kids.join(","));
    if (/\bq_\d+\b/.test(c.textContent)) out.push("5 internal id on card");
    const b = getComputedStyle(c, "::before");
    if (b.height !== "3px" || c.getBoundingClientRect().width === 0) out.push("3 top edge " + b.height);
  });
  document.querySelectorAll("dl.stats dt").forEach((d) => { if (d.getBoundingClientRect().height > lh(d) * 1.3) out.push("10 stat label wraps: " + d.textContent); });
  const sent = document.querySelector(".sentence");
  if (sent) {
    const fs = parseFloat(getComputedStyle(sent).fontSize), h2 = document.querySelector(".section>h2");
    if (fs < 16 || fs > 17.01 || (h2 && fs > parseFloat(getComputedStyle(h2).fontSize))) out.push("9 sentence font " + fs);
    const row = document.querySelector(".chiprow .grp");
    if (row && row.getBoundingClientRect().top < sent.getBoundingClientRect().bottom) out.push("9 chips not under the sentence");
  }
  if (phone) document.querySelectorAll("main > .section > h2, main > section > h2").forEach((h) => {
    const sec = h.parentElement, prev = sec.previousElementSibling;
    if (prev && prev !== null && sec.getBoundingClientRect().top - prev.getBoundingClientRect().bottom < 23.5 && getComputedStyle(sec).order === getComputedStyle(prev).order) out.push("4 gap above heading " + h.textContent);
  });
  return out;
}"""

FIRST_SCREEN = """() => {
  const vh = window.innerHeight, nav = document.querySelector("nav.tabs").getBoundingClientRect().top;
  const lim = Math.min(vh, nav);
  const bottom = (el) => el ? el.getBoundingClientRect().bottom : 1e9;
  const chip = document.querySelector(".core .chip");
  return { h1: bottom(document.querySelector("h1")), lede: bottom(document.querySelector(".hero .lede")), chip: chip ? chip.getBoundingClientRect().bottom : 1e9, lim };
}"""

def first_screen(browser, url, scheme, problems):
    ctx = browser.new_context(color_scheme=scheme, viewport={"width": 360, "height": 740})
    page = ctx.new_page()
    page.expose_function("__call", handle_call)
    install(page)
    page.goto(url)
    page.wait_for_selector(".stats dd")
    page.wait_for_function("() => !document.querySelector('.skel')", timeout=8000)
    r = page.evaluate(FIRST_SCREEN)
    tag = f"[{scheme} 360x740 first screen]"
    for k in ("h1", "lede", "chip"):
        if r[k] > r["lim"]:
            problems.append(f"{tag} {k} ends at {r[k]:.0f}px, visible area ends at {r['lim']:.0f}px")
    ctx.close()


def connect_key(page, key):
    page.click("#walletBtn")
    page.click("details.tune >> text=Use a Studio private key")
    page.fill("#pkIn", key)
    page.click("text=Use this key")
    page.wait_for_selector("#walletBtn.on")


def main():
    shots = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
    if shots:
        os.makedirs(shots, exist_ok=True)
    seed()
    problems = []
    with sync_playwright() as p:
        exe = os.environ.get("CHROME_PATH") or ("/usr/bin/google-chrome" if os.path.exists("/usr/bin/google-chrome") else None)
        browser = p.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else p.chromium.launch(args=["--no-sandbox"])
        url = "file://" + os.path.join(ROOT, "index.html") + "?contract=0x" + "ab" * 20
        for scheme in ("light", "dark"):
            ctx = browser.new_context(color_scheme=scheme, viewport={"width": 390, "height": 800})
            page = ctx.new_page()
            errors = []
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" and "ERR_FAILED" not in msg.text and "fonts" not in msg.text else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.expose_function("__call", handle_call)
            install(page)
            page.goto(url)
            page.wait_for_selector(".stats dd")
            connect_key(page, KEY_ASKER)
            for w in WIDTHS:
                page.set_viewport_size({"width": w, "height": 900})
                for route in ROUTES:
                    page.evaluate("(r) => { location.hash = r }", route)
                    page.wait_for_timeout(500)
                    page.wait_for_function("() => !document.querySelector('.skel')", timeout=8000)
                    r = page.evaluate(MEASURE)
                    tag = f"[{scheme} {w}px {route}]"
                    if r["overflow"] > 0 or r["wide"]:
                        problems.append(f"{tag} horizontal overflow {r['overflow']} {r['wide']}")
                    if r["small"]:
                        problems.append(f"{tag} small targets {r['small'][:4]}")
                    if r["tnum"] not in ("normal", ""):
                        problems.append(f"{tag} page-wide font-variant-numeric {r['tnum']}")
                    if r["adjust"] not in ("100%", "auto"):
                        problems.append(f"{tag} text-size-adjust {r['adjust']}")
                    problems += [f"{tag} pitfall {x}" for x in page.evaluate(PITFALLS)]
                    if shots and scheme == "light" and w in (390, 1280) and route in ("#/", "#/ask", "#/q/q_2", "#/q/q_0", "#/lab"):
                        page.screenshot(path=os.path.join(shots, f"{w}_{route.replace('#/', '').replace('/', '_') or 'home'}.png"), full_page=True)
                if shots and scheme == "dark" and w == 390:
                    page.evaluate("(r) => { location.hash = r }", "#/")
                    page.wait_for_timeout(600)
                    page.screenshot(path=os.path.join(shots, "390_home_dark.png"), full_page=True)
            problems += [f"[{scheme}] console: {e}" for e in errors]
            ctx.close()
        for scheme in ("light", "dark"):
            first_screen(browser, url, scheme, problems)
        problems += e2e(browser, url)
        browser.close()
    print("\n".join(problems) if problems else "QA passed: no overflow, targets >= 36px, no console errors, end to end OK")
    return 1 if problems else 0


def run_step(page, text, timeout=60000):
    page.click(f"button:has-text('Run this step') >> nth=0")
    page.wait_for_selector(".tx.good, .tx.bad", timeout=timeout)


def e2e(browser, url):
    problems = []
    ctx = browser.new_context(viewport={"width": 390, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.expose_function("__call", handle_call)
    install(page)
    page.goto(url + "#/ask")
    page.wait_for_selector("#qTitle")
    page.click("#walletBtn")
    page.click("button.option:has-text('Test session')")
    page.wait_for_selector("#walletBtn.on")
    page.fill("#qTitle", "What is the tallest mountain on Earth above sea level?")
    page.fill("input[aria-label='Criterion 1']", "Names the correct mountain")
    page.click("button:has-text('Review and post')")
    page.click("#dlgConfirm")
    page.wait_for_selector(".tx.bad")
    if "Not enough GEN" not in page.inner_text(".tx .msg"):
        problems.append("insufficient balance pre-check message missing")
    page.evaluate("window.__skewMs = 0")
    page.goto(url + "#/lab")
    page.wait_for_selector(".timeline")
    for key, label, expect in (("A", "A. A good answer wins", "won"), ("B", "B. No answer passes", "refunded")):
        section = page.locator("section.panel", has_text=label)
        for _ in range(10):
            btn = section.locator("button:has-text('Run this step')").first
            if btn.count() == 0:
                break
            for _wait in range(40):
                if not section.locator("button:has-text('Run this step')").first.is_disabled():
                    break
                if "grading" in section.locator("li.now b").first.inner_text().lower():
                    SKEW["s"] += 3600
                    page.evaluate("window.__skewMs += 3600000")
                    page.wait_for_timeout(1500)
                else:
                    page.wait_for_timeout(500)
            before = section.locator("li.done").count()
            section.locator("button:has-text('Run this step')").first.click()
            try:
                page.wait_for_function(
                    "([lab, n]) => { const s = [...document.querySelectorAll('section.panel')].find((e) => e.textContent.includes(lab)); return s.querySelectorAll('li.done').length > n || !!s.querySelector('.tx.bad'); }",
                    arg=[label, before], timeout=90000)
            except Exception:
                problems.append(f"lab {key} step timed out")
                break
            if section.locator(".tx.bad").count():
                problems.append(f"lab {key} step failed: " + section.locator(".tx .msg").first.inner_text())
                break
        stats = json.loads(C["c"].get_stats())
        if stats[expect] < 2:
            problems.append(f"lab {key} did not reach '{expect}' (stats won={stats['won']} refunded={stats['refunded']})")
    c = C["c"]
    acct = T.check_books(__import__("unittest").TestCase(), c)
    if not acct["balance_covers_liabilities"]:
        problems.append("books unbalanced after e2e")
    problems += [f"e2e pageerror: {e}" for e in errors]
    ctx.close()
    return problems


if __name__ == "__main__":
    sys.exit(main())
