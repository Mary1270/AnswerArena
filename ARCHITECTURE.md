# Architecture

- One contract, `AnswerArena`. Questions, answers and an event log are stored as JSON strings in tree maps, with status counters and a locked-funds total.
- Money: every GEN in the contract is either locked (bounties, answer fees, dispute bonds of live questions) or owed (credited balances waiting for `withdraw`). `get_accounting` checks balance >= locked + owed and that the locked total equals the sum over live questions.
- Non-deterministic work is isolated in `_grade_compute` (web fetch for link answers, one LLM call returning JSON) and checked by `_grade_agree` under `gl.vm.run_nondet_unsafe`. The model reply is normalized in code to integers 0 to 10 per criterion, so validators compare totals within a tolerance and the picked winner within a margin instead of comparing free text.
- Payable calls that fail validation return a JSON `rejected` object and credit the full value back instead of reverting, so the frontend can show a precise message.
- Frontend: one `index.html`, hash routes, genlayer-js from esm.sh, contract data only inserted as text.
