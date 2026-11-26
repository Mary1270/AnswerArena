import ast
import io
import os
import tokenize
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER = (
    "# v0.2.16",
    '# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }',
)
FILES = ("contract.py", "contract_sandbox.py")


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


class TestContractFormat(unittest.TestCase):
    def test_two_header_lines_then_code(self):
        for name in FILES:
            source = read(name)
            lines = source.splitlines()
            self.assertEqual(tuple(lines[:2]), HEADER, name)
            self.assertTrue(lines[2].startswith("from genlayer import"), name)
            comments = [t.start[0] for t in tokenize.generate_tokens(io.StringIO(source).readline)
                        if t.type == tokenize.COMMENT]
            self.assertEqual(comments, [1, 2], name)

    def test_no_docstrings(self):
        for name in FILES:
            for node in ast.walk(ast.parse(read(name))):
                body = getattr(node, "body", None)
                if isinstance(body, list):
                    for child in body:
                        self.assertFalse(isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant)
                                         and isinstance(child.value.value, str), f"{name}:{child.lineno}")

    def test_ascii_and_clean_lines(self):
        for name in FILES:
            source = read(name)
            source.encode("ascii")
            self.assertTrue(source.endswith("\n"))
            for number, line in enumerate(source.splitlines(), 1):
                self.assertEqual(line, line.rstrip(), f"{name}:{number}")
                self.assertNotIn("\t", line)

    def test_sandbox_differs_only_in_four_constants(self):
        prod = read("contract.py").splitlines()
        sand = read("contract_sandbox.py").splitlines()
        self.assertEqual(len(prod), len(sand))
        diff = [(a.strip(), b.strip()) for a, b in zip(prod, sand) if a != b]
        self.assertEqual([d[0].split(" =")[0] for d in diff],
                         ["MODE", "MIN_WINDOW_SECONDS", "DISPUTE_WINDOW_SECONDS", "GRADE_TIMEOUT_SECONDS"])

    def test_storage_is_never_reassigned_to_plain_containers(self):
        source = read("contract.py")
        for bad in ("= {}", "= []", "TreeMap()", "DynArray()"):
            for line in source.splitlines():
                if line.strip().startswith("self.") and bad in line:
                    self.fail(line)


if __name__ == "__main__":
    unittest.main()
