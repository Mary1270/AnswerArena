# AnswerArena

Open question bounties on GenLayer. An asker posts a question, a bounty in GEN, a grading rubric of up to four criteria and a deadline. Anyone can answer with text or a link for a small fee that is added to the bounty. After the deadline, validators run an LLM that scores every answer on every criterion. The best answer wins the pot. The asker may dispute once with a bond. If no answer reaches the pass mark, the pot goes back to the asker.

## What is in the box

| File | Purpose |
| --- | --- |
| `contract.py` | Production Intelligent Contract (`AnswerArena`) |
| `contract_sandbox.py` | Same contract with four constants changed so a whole bounty settles in minutes on Studio (generated, never edited by hand) |
| `index.html` | Single-file frontend: home, ask, questions, question page, mine, guided test lab |
| `tests/` | Offline test suite with a GenLayer SDK stub (53 tests) |
| `tools/make_sandbox.py` | Builds and checks `contract_sandbox.py` |
| `tools/qa_playwright.py` | Optional browser QA that runs the real contract behind the page |
| `ci/tests.yml` | Offline tests workflow (copy to `.github/workflows/`) |
| `ARCHITECTURE.md`, `TESTING.md` | Design notes and the Studio walkthrough |

## Live deployment

| | |
| --- | --- |
| Contract | `ADDRESS` |
| Explorer | https://explorer-studio.genlayer.com/address/ADDRESS |
| Frontend | https://mary1270.github.io/AnswerArena/ |
| Network | GenLayer Studio |

## How a bounty works

1. **Post.** `post_question(title, details, rubric, min_score, window_minutes)` with the bounty attached. The rubric is 1 to 4 criteria separated by `|`. `min_score` (10 to 90) is the pass mark out of 100.
2. **Answer.** `submit_answer(question_id, kind, content)` with at least 1 GEN attached. `kind` is `TEXT` or `URL` (https only). One answer per address, at most 10 per question, never from the asker. The fee joins the pot; any extra sent is credited back.
3. **Grade.** After the deadline anyone calls `grade(question_id)`. The leader fetches every linked page, asks the LLM for integer scores 0 to 10 per criterion in a fixed JSON shape, and normalizes them in code. Validators run the same steps and accept when every answer total is within 25 points and they agree on the winner within a 10 point margin. Totals are the average of the criteria scaled to 100. The highest total at or above the pass mark wins; ties go to the earliest answer.
4. **Dispute or accept.** The asker has a dispute window (48 hours in production). `accept_result` settles at once. `dispute(question_id, reason)` posts a bond (10% of the pot, rounded up to a whole GEN, at least 1 GEN) and can be used once.
5. **Finalize.** `finalize(question_id)` pays the winner after the window. After a dispute it grades again with the reason in view: if the winner is unchanged the bond goes to that winner, otherwise the bond returns to the asker and the new result applies (or the pot is refunded if nobody passes).
6. **No pass or no answers.** The whole pot returns to the asker.
7. **Timeouts.** If grading never completes within 3 days of the deadline, `void_question` refunds the bounty to the asker and every fee to its answerer. A dispute that is never reviewed lapses to the original result.
8. **Payments** are pull-based (`withdraw`) with a permissionless `push_payment(beneficiary)`.

## Read-only functions

`get_config`, `get_stats`, `get_accounting`, `list_questions`, `get_question`, `get_answers`, `get_asker_questions`, `get_answerer_answers`, `get_activity`, `get_pending_withdrawal`.

`get_accounting` reports the contract balance against locked bounties, fees, bonds and claimable balances; the home page shows it as the "Balanced" check.

## Run the tests

```
python3 -m unittest discover -s tests
AA_CONTRACT=$PWD/contract_sandbox.py python3 -m unittest discover -s tests
python3 tools/make_sandbox.py --check
```

## Deploy and try it

1. Open GenLayer Studio, deploy `contract_sandbox.py` (no constructor arguments) and copy the address.
2. Open `index.html?contract=ADDRESS`, or paste the address in the wallet menu. For a permanent default, set `DEFAULT_CONTRACT_ADDRESS` in `index.html`.
3. Follow the **Lab** tab, or the table in `TESTING.md`.

Use `contract.py` for a production-style deployment (answers stay open for at least one hour).

## Limits and honesty

- Grading is automated. An LLM can misjudge; the dispute path and validator agreement reduce, not remove, that risk.
- Answer text and linked pages are untrusted input; the grader is told to ignore instructions inside them, which lowers but does not eliminate prompt-injection risk.
- A link that cannot be fetched scores zero. Pages are read as text, truncated to a few thousand characters.
- Offline tests use mocked web pages and a scripted model. Live behaviour on Studio is exercised with the walkthrough in `TESTING.md`.
- This is a test-network demonstration, not a production marketplace.

## License

MIT
