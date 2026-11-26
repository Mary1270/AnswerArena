# Testing

## Offline

```
python3 -m unittest discover -s tests
AA_CONTRACT=$PWD/contract_sandbox.py python3 -m unittest discover -s tests
python3 tools/make_sandbox.py --check
```

## Browser QA (optional)

```
AA_CONTRACT=$PWD/contract_sandbox.py python3 tools/qa_playwright.py --shots out
```

Needs Playwright and Chrome. It checks widths 320 to 1440 in both themes and runs both lab scenarios against the real contract code.

## Studio

Deploy `contract_sandbox.py`. Answer windows can be one minute, the dispute window is three minutes and the grading timeout ten minutes. Open `index.html?contract=ADDRESS` and use the Lab tab, or send the same calls by hand in Studio.
