import ast
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from graphtrust.graph import _Bindings, _Walker, build_graph


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def write(self, path, text):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8", newline="")

    @staticmethod
    def relationships(graph):
        return {(edge["source"], edge["target"]) for edge in graph["edges"]}

    def test_deterministic_snapshot_and_node_source_provenance(self):
        source = "# café\r\ndef helper():\r\n    return 1\r\n\r\ndef run():\r\n    return helper()\r\n"
        self.write("café.py", source)
        self.write("tests/test_sample.py", "def test_run():\n    pass\n")
        self.write("vendor/ignored.py", "this is invalid Python")
        first = build_graph(self.root, "abc123")
        self.assertEqual(first, build_graph(self.root, "abc123"))
        self.assertEqual(first["snapshot"]["commit"], "abc123")
        self.assertEqual(len(first["snapshot"]["files"]), 2)
        run = next(node for node in first["nodes"] if node["id"] == "café.py::run")
        self.assertEqual(run["text"], "def run():\r\n    return helper()\r\n")
        self.assertEqual(run["start_line"], 5)
        self.assertEqual(run["end_line"], 6)
        self.assertEqual(run["sha256"], hashlib.sha256(run["text"].encode()).hexdigest())
        edge = first["edges"][0]
        self.assertEqual(edge["path"], "café.py")
        self.assertEqual(edge["line"], 6)
        self.assertEqual(edge["expression"], "helper")
        self.write("café.py", source + "# changed\r\n")
        self.assertNotEqual(first["snapshot"]["source_sha256"], build_graph(self.root)["snapshot"]["source_sha256"])

    def test_import_alias_relative_import_and_nested_async(self):
        self.write("src/pkg/__init__.py", "")
        self.write("src/pkg/helpers.py", "def compute():\n    return 1\n")
        self.write("src/pkg/main.py", """from .helpers import compute as alias
import pkg.helpers as tools
import pkg.helpers

async def outer():
    async def inner():
        return alias()
    tools.compute()
    pkg.helpers.compute()
    return await inner()
""")
        graph = build_graph(self.root)
        relationships = self.relationships(graph)
        self.assertIn(("src/pkg/main.py::outer.inner", "src/pkg/helpers.py::compute"), relationships)
        self.assertIn(("src/pkg/main.py::outer", "src/pkg/helpers.py::compute"), relationships)
        self.assertIn(("src/pkg/main.py::outer", "src/pkg/main.py::outer.inner"), relationships)
        self.assertFalse(graph["errors"])
        self.assertEqual(len(graph["edges"]), 4)

    def test_arguments_assignments_and_class_scopes_do_not_resolve_by_name(self):
        self.write("main.py", """def helper():
    pass

def argument(helper):
    helper()

def assigned():
    helper()
    helper = 3

class Example:
    def helper(self):
        pass
    def run(self):
        self.helper()
        helper()
        unknown.helper()

Example.helper(None)
""")
        graph = build_graph(self.root)
        relationships = self.relationships(graph)
        self.assertNotIn(("main.py::argument", "main.py::helper"), relationships)
        self.assertNotIn(("main.py::assigned", "main.py::helper"), relationships)
        self.assertIn(("main.py::Example.run", "main.py::helper"), relationships)
        self.assertNotIn(("main.py::Example.run", "main.py::Example.helper"), relationships)
        self.assertIn(("main.py::<module>", "main.py::Example.helper"), relationships)
        self.assertEqual(len(graph["unknown"]), 4)

    def test_decorated_bindings_duplicates_and_monkey_patches_are_unknown(self):
        self.write("main.py", """def decorate(func):
    return func
@decorate
def target():
    pass
target()

def repeated():
    pass
def repeated():
    pass
repeated()

class C:
    @staticmethod
    def method():
        pass
C.method = target
C.method()
""")
        graph = build_graph(self.root)
        expressions = {item["expression"]: item["reason"] for item in graph["unknown"]}
        self.assertEqual(expressions["target"], "decorated_binding")
        self.assertEqual(expressions["repeated"], "ambiguous_or_rebound_binding")
        self.assertEqual(expressions["C.method"], "reassigned_attribute")
        ids = [node["id"] for node in graph["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_static_class_methods_and_external_dynamic_bindings(self):
        self.write("main.py", """import external
class C:
    @staticmethod
    def static():
        pass
    @classmethod
    def method(cls):
        cls.static()
C.static()
C.method()
external.some_function()
getattr(C, 'static')()
""")
        graph = build_graph(self.root)
        targets = {edge["target"] for edge in graph["edges"]}
        self.assertEqual(targets, {"main.py::C.static", "main.py::C.method"})
        self.assertIn("cls.static", {item["expression"] for item in graph["unknown"]})
        self.assertIn("external.some_function", {item["expression"] for item in graph["unknown"]})
        self.assertIn("getattr(C, 'static')", {item["expression"] for item in graph["unknown"]})

    def test_comprehension_and_lambda_parameters_do_not_shadow_outer_scope(self):
        self.write("main.py", """def f():
    pass
def run(items):
    [f() for f in items]
    [f() for item in items]
    (lambda f: f())(f)
    f()
""")
        graph = build_graph(self.root)
        self.assertEqual(len([edge for edge in graph["edges"] if edge["target"] == "main.py::f"]), 2)
        self.assertEqual(len([item for item in graph["unknown"] if item["expression"] == "f"]), 2)

    def test_bad_syntax_and_encoding_are_visible_and_hashed(self):
        self.write("broken.py", "def broken(:\n    pass\n")
        (self.root / "bytes.py").write_bytes(b"# coding: utf-8\n\xff\n")
        (self.root / "latin.py").write_bytes(b"# coding: latin-1\n# caf\xe9\ndef ok():\n    pass\n")
        graph = build_graph(self.root)
        self.assertEqual({item["error"] for item in graph["errors"]}, {"syntax_error", "decode_error"})
        self.assertEqual(len(graph["snapshot"]["files"]), 3)
        self.assertIn("latin.py::ok", {node["id"] for node in graph["nodes"]})

    def test_missing_root_is_rejected(self):
        with self.assertRaises(ValueError):
            build_graph(self.root / "missing")

    def test_deep_lambda_expression_preserves_supported_call(self):
        source = "def wanted(): pass\nf = lambda: wanted()" + " + 0" * 600 + "\n"
        self.write("deep.py", source)
        graph = build_graph(self.root)
        self.assertFalse(graph["errors"])
        self.assertEqual(len(graph["edges"]), 1)
        edge = graph["edges"][0]
        self.assertEqual((edge["source"], edge["target"], edge["line"], edge["expression"]),
                         ("deep.py::<module>", "deep.py::wanted", 2, "wanted"))
        self.assertEqual(graph["snapshot"]["files"][0]["sha256"], hashlib.sha256(source.encode()).hexdigest())

    def test_deep_function_expression_preserves_lexical_scope(self):
        source = "def wanted(): pass\ndef run():\n    return wanted()" + " + 0" * 600 + "\nwanted()\n"
        self.write("deep.py", source)
        graph = build_graph(self.root)
        self.assertFalse(graph["errors"])
        self.assertEqual(self.relationships(graph),
                         {("deep.py::run", "deep.py::wanted"), ("deep.py::<module>", "deep.py::wanted")})
        self.assertEqual({edge["line"] for edge in graph["edges"]}, {3, 4})

    def test_iterative_generic_walk_preserves_original_scope_and_mutation_outputs(self):
        self.write("main.py", """def wanted(): pass
def outer():
    x = wanted
    def inner():
        nonlocal x
        x = 3
    inner()
    x()
def closure():
    y = wanted
    return lambda: y()
def shadow():
    return [wanted() for wanted in [3]]
class Known:
    @staticmethod
    def method(): wanted()
Known.method()
wanted()
outer()
Known.method = 3
Known.method()
f = lambda: wanted() + wanted()
""")
        with patch.object(_Bindings, "generic_visit", ast.NodeVisitor.generic_visit), \
                patch.object(_Walker, "generic_visit", ast.NodeVisitor.generic_visit):
            original = build_graph(self.root)
        self.assertEqual(original, build_graph(self.root))

    def test_global_nonlocal_pattern_and_lambda_rebinding_is_conservative(self):
        self.write("main.py", """def changed():
    pass
def mutator():
    global changed
    changed = None
def caller():
    changed()

def outer():
    def local():
        pass
    def mutate():
        nonlocal local
        local = None
    local()

def stable():
    pass
def pattern(value):
    match value:
        case {'name': stable}:
            stable()
def lambda_rebind():
    (lambda: (stable := None, stable()))()
""")
        graph = build_graph(self.root)
        self.assertEqual(graph["edges"], [])
        self.assertEqual(len([item for item in graph["unknown"] if item["expression"] == "stable"]), 2)

    def test_package_existing_unknown_member_blocks_submodule_resolution(self):
        self.write("pkg/__init__.py", "target = 3\n")
        self.write("pkg/target.py", "def function():\n    pass\n")
        self.write("main.py", "from pkg import target\ntarget.function()\n")
        graph = build_graph(self.root)
        self.assertEqual(graph["edges"], [])
        self.assertEqual(len(graph["unknown"]), 1)


if __name__ == "__main__":
    unittest.main()
