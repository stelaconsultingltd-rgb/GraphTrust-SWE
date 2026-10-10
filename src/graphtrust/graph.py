"""Deterministic, conservative Python call relationships without executing code.

Supported edges describe uniquely resolved lexical bindings in this snapshot,
not a sound runtime call graph. Dynamic receivers and ambiguous/rebound names
are deliberately retained in ``unknown``. Python tests are included; generated,
vendor, virtual-environment and version-control directories are excluded.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import tokenize
from dataclasses import dataclass, field
from typing import Any


_IGNORED = {
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".nox", ".venv", "venv", "env", "node_modules",
    "site-packages", "vendor", "vendors", "third_party", "build", "dist",
}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def edge_identifier(edge: dict[str, Any]) -> str:
    """Stable identifier for a relationship and its source call site."""
    fields = [edge.get(key, "") for key in
              ("source", "target", "type", "path", "line", "expression")]
    return "e_" + _hash(json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode())[:24]


@dataclass
class _Scope:
    node_id: str
    kind: str
    module: str
    parent: "_Scope | None"
    bindings: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    redirected: dict[str, str] = field(default_factory=dict)
    star_import: bool = False

    def bind(self, name: str, value: tuple[str, str]) -> None:
        self.bindings.setdefault(name, []).append(value)


class _IterativeGenericVisitor(ast.NodeVisitor):
    """Keep generic expression depth off the Python stack.

    Custom visitors still manage their own lexical scope and child traversal.
    Their recursive dispatch and name resolution retain separate depth limits.
    """

    def generic_visit(self, node: ast.AST) -> None:
        pending = list(reversed(list(ast.iter_child_nodes(node))))
        while pending:
            child = pending.pop()
            visitor = getattr(self, "visit_" + child.__class__.__name__, None)
            if visitor is None:
                # Expanding only generic nodes preserves the original
                # depth-first order and custom visitors' scope entry/exit.
                pending.extend(reversed(list(ast.iter_child_nodes(child))))
            else:
                visitor(child)


class _Bindings(_IterativeGenericVisitor):
    """Collect one lexical scope, avoiding nested definition bodies."""

    def __init__(self, scope: _Scope, extractor: "_Extractor") -> None:
        self.scope, self.extractor = scope, extractor

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        child = self.extractor.register(node, self.scope, "function")
        safe = not node.decorator_list or self.extractor.safe_descriptor(node, self.scope)
        self.scope.bind(node.name, ("node", child.node_id) if safe else ("unknown", "decorated_binding"))
        for value in [*node.decorator_list, *node.args.defaults,
                      *[x for x in node.args.kw_defaults if x is not None]]:
            self.visit(value)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        child = self.extractor.register(node, self.scope, "class")
        self.scope.bind(node.name, ("node", child.node_id) if not node.decorator_list
                        else ("unknown", "decorated_binding"))
        for value in [*node.bases, *node.decorator_list, *[x.value for x in node.keywords]]:
            self.visit(value)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for value in [*node.args.defaults, *[x for x in node.args.kw_defaults if x is not None]]:
            self.visit(value)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.scope.bind(node.id, ("unknown", "assigned_or_deleted_binding"))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.scope.bind(name, ("module", alias.name if alias.asname else name))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = self.extractor.import_module(self.scope.module, node)
        for alias in node.names:
            if alias.name == "*":
                self.scope.star_import = True
            else:
                self.scope.bind(alias.asname or alias.name, ("import", module + ":" + alias.name))

    def visit_Global(self, node: ast.Global) -> None:
        self.scope.redirected.update({name: "global" for name in node.names})

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.scope.redirected.update({name: "nonlocal" for name in node.names})

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name:
            self.scope.bind(node.name, ("unknown", "pattern_binding"))
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self.scope.bind(node.name, ("unknown", "pattern_binding"))

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.scope.bind(node.rest, ("unknown", "pattern_binding"))
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.scope.bind(node.name, ("unknown", "exception_binding"))
        self.generic_visit(node)

    def _comprehension(self, node: Any) -> None:
        # Comprehension targets have a separate scope. Walrus bindings, however,
        # leak into the enclosing lexical scope and must prevent false resolution.
        for child in ast.walk(node):
            if isinstance(child, ast.NamedExpr):
                self.visit(child.target)

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension


class _Extractor:
    def __init__(self, sources: dict[str, str]) -> None:
        self.sources = sources
        self.source_lines = {path: source.splitlines(keepends=True) for path, source in sources.items()}
        self.source_bytes = {path: [line.encode("utf-8") for line in lines]
                             for path, lines in self.source_lines.items()}
        self.nodes: dict[str, dict[str, Any]] = {}
        self.scopes: dict[int, _Scope] = {}
        self.node_scopes: dict[str, _Scope] = {}
        self.modules: dict[str, list[_Scope]] = {}
        self.paths: dict[str, _Scope] = {}
        self.path_modules: dict[str, str] = {}
        self.trees: dict[str, ast.Module] = {}
        self.edges: list[dict[str, Any]] = []
        self.unknown: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.invalid_attributes: set[tuple[str, str]] = set()
        self.dynamic_classes: set[str] = set()
        self._path = ""
        self._qualified: dict[str, str] = {}

    @staticmethod
    def module_names(path: str) -> list[str]:
        parts = list(Path(path).with_suffix("").parts)
        if parts[-1] == "__init__" and len(parts) > 1:
            parts.pop()
        names = [".".join(parts)]
        if len(parts) > 1 and parts[0] in {"src", "lib", "python"}:
            names.insert(0, ".".join(parts[1:]))
        return names

    def initialize(self) -> None:
        for path, source in sorted(self.sources.items()):
            node_id = path + "::<module>"
            self.nodes[node_id] = self.make_node(node_id, "module", path, source, 1,
                                                max(1, len(source.splitlines())))
            names = self.module_names(path)
            scope = _Scope(node_id, "module", names[0], None)
            self.node_scopes[node_id] = scope
            self.paths[path], self.path_modules[path] = scope, names[0]
            self._qualified[node_id] = ""
            for name in names:
                self.modules.setdefault(name, []).append(scope)
            try:
                tree = ast.parse(source, filename=path, type_comments=True)
            except SyntaxError as exc:
                self.errors.append({"path": path, "line": exc.lineno,
                                    "error": "syntax_error", "message": exc.msg})
                continue
            self.trees[path] = tree
            self.scopes[id(tree)] = scope
        for path, tree in self.trees.items():
            self._path = path
            collector = _Bindings(self.paths[path], self)
            for statement in tree.body:
                collector.visit(statement)
        # A write through global/nonlocal changes the referenced outer binding,
        # even for callers elsewhere. Propagate after all scopes are collected
        # so definition order cannot hide an outer binding.
        for scope in self.scopes.values():
            for name, redirect in scope.redirected.items():
                if name not in scope.bindings:
                    continue
                target = scope.parent
                if redirect == "global":
                    while target is not None and target.parent is not None:
                        target = target.parent
                else:
                    while target is not None and (target.kind == "class" or name not in target.bindings):
                        target = target.parent
                if target is not None:
                    target.bind(name, ("unknown", "global_or_nonlocal_assignment"))

    @staticmethod
    def make_node(node_id: str, kind: str, path: str, text: str,
                  start: int, end: int) -> dict[str, Any]:
        return {"id": node_id, "kind": kind, "path": path, "start_line": start,
                "end_line": end, "text": text, "sha256": _hash(text.encode("utf-8"))}

    def register(self, node: Any, parent: _Scope, kind: str) -> _Scope:
        qualified = self._qualified[parent.node_id]
        qualified = (qualified + "." if qualified else "") + node.name
        node_id = self._path + "::" + qualified
        if node_id in self.nodes:
            node_id += "@L" + str(node.lineno)
            qualified += "@L" + str(node.lineno)
        start = min([node.lineno, *[item.lineno for item in node.decorator_list]])
        end = node.end_lineno or node.lineno
        source = "".join(self.source_lines[self._path][start - 1:end])
        self.nodes[node_id] = self.make_node(node_id, kind, self._path, source, start, end)
        self._qualified[node_id] = qualified
        child = _Scope(node_id, kind, parent.module, parent)
        self.scopes[id(node)] = child
        self.node_scopes[node_id] = child
        if kind == "class" and any(keyword.arg == "metaclass" for keyword in node.keywords):
            self.dynamic_classes.add(node_id)
        if kind == "function":
            args = node.args
            for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs,
                        *([args.vararg] if args.vararg else []),
                        *([args.kwarg] if args.kwarg else [])]:
                child.bind(arg.arg, ("unknown", "parameter_binding"))
        collector = _Bindings(child, self)
        for statement in node.body:
            collector.visit(statement)
        return child

    def safe_descriptor(self, node: Any, parent: _Scope) -> bool:
        # Calls through explicit Class.method syntax can identify a method body
        # when the only decorator is an unshadowed builtin descriptor. Instance
        # receiver calls stay unknown (including self and cls).
        if parent.kind != "class" or len(node.decorator_list) != 1:
            return False
        decorator = node.decorator_list[0]
        if not isinstance(decorator, ast.Name) or decorator.id not in {"staticmethod", "classmethod"}:
            return False
        return not self.name_is_written(decorator.id, parent)

    def name_is_written(self, name: str, scope: _Scope) -> bool:
        # Scopes may not yet be fully collected here. Inspect the complete AST
        # for descriptor-name bindings rather than relying on statement order.
        path = self.nodes[scope.node_id]["path"]
        tree = self.trees.get(path)
        if tree is None:
            return True
        for item in ast.walk(tree):
            if isinstance(item, ast.Name) and item.id == name and isinstance(item.ctx, (ast.Store, ast.Del)):
                return True
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and item.name == name:
                return True
            if isinstance(item, ast.arg) and item.arg == name:
                return True
            if isinstance(item, (ast.Import, ast.ImportFrom)):
                if any((alias.asname or alias.name.split(".")[0]) == name or alias.name == "*"
                       for alias in item.names):
                    return True
        return False

    def import_module(self, module: str, node: ast.ImportFrom) -> str:
        if not node.level:
            return node.module or ""
        path = self._path
        package = module if path.endswith("/__init__.py") else module.rpartition(".")[0]
        parts = package.split(".") if package else []
        if node.level > len(parts):
            return "<unresolved-relative>"
        base = parts[:len(parts) - node.level + 1]
        return ".".join([*base, *([node.module] if node.module else [])])

    def module_scope(self, module: str) -> _Scope | None:
        candidates = self.modules.get(module, [])
        return candidates[0] if len(candidates) == 1 else None

    def resolve_name(self, name: str, scope: _Scope,
                     seen: frozenset[tuple[str, str]] = frozenset()) -> tuple[tuple[str, str] | None, str]:
        if scope.star_import:
            return None, "wildcard_import"
        if name in scope.redirected:
            return None, "global_or_nonlocal_binding"
        bindings = scope.bindings.get(name)
        if bindings:
            if len(bindings) != 1:
                return None, "ambiguous_or_rebound_binding"
            binding = bindings[0]
            if binding[0] == "unknown":
                return None, binding[1]
            if binding[0] == "import":
                key = (scope.node_id, name)
                if key in seen:
                    return None, "cyclic_import_binding"
                module, member = binding[1].rsplit(":", 1)
                return self.resolve_member(("module", module), member, seen | {key})
            return binding, "supported"
        parent = scope.parent
        # A class namespace is not a lexical enclosing scope for function bodies
        # or comprehensions. Nested classes also do not close over class members.
        if scope.kind in {"function", "class", "comprehension", "lambda"}:
            while parent is not None and parent.kind == "class":
                parent = parent.parent
        return self.resolve_name(name, parent, seen) if parent is not None else (None, "unbound_or_builtin")

    def resolve_member(self, base: tuple[str, str], member: str,
                       seen: frozenset[tuple[str, str]] = frozenset()) -> tuple[tuple[str, str] | None, str]:
        if (base[1], member) in self.invalid_attributes:
            return None, "reassigned_attribute"
        if base[0] == "module":
            scope = self.module_scope(base[1])
            submodule = self.module_scope(base[1] + "." + member)
            local = None
            reason = "import_outside_snapshot"
            if scope is not None and member in scope.bindings:
                local, reason = self.resolve_name(member, scope, seen)
                if local is None:
                    # Python from-import respects an existing package member;
                    # a same-name source submodule cannot prove that binding.
                    return None, reason
            if local is not None and submodule is not None:
                # A package reexport and a module with the same name are ambiguous
                # unless they identify that exact same module.
                if local != ("module", base[1] + "." + member):
                    return None, "ambiguous_module_member"
            if local is not None:
                return local, reason
            if submodule is not None:
                return ("module", base[1] + "." + member), "supported"
            return None, reason
        if base[0] == "node" and self.nodes[base[1]]["kind"] == "class":
            if base[1] in self.dynamic_classes:
                return None, "explicit_metaclass_attribute"
            scope = self.node_scopes.get(base[1])
            if scope is not None and member in scope.bindings:
                # Member resolution must not fall back to the module namespace.
                return self.resolve_name(member, scope, seen)
            return None, "inherited_or_dynamic_attribute"
        return None, "dynamic_receiver"

    def resolve(self, expression: ast.expr, scope: _Scope) -> tuple[tuple[str, str] | None, str]:
        if isinstance(expression, ast.Name):
            return self.resolve_name(expression.id, scope)
        if isinstance(expression, ast.Attribute):
            base, reason = self.resolve(expression.value, scope)
            if base is None:
                return None, "dynamic_receiver:" + reason
            return self.resolve_member(base, expression.attr)
        return None, "dynamic_callable_expression"

    def expression_text(self, path: str, expression: ast.expr) -> str:
        """Use cached lines and UTF-8 byte columns (the AST offset convention)."""
        start, end = expression.lineno - 1, (expression.end_lineno or expression.lineno) - 1
        lines = self.source_bytes[path]
        if start == end:
            raw = lines[start][expression.col_offset:expression.end_col_offset]
        else:
            raw = b"".join([lines[start][expression.col_offset:], *lines[start + 1:end],
                            lines[end][:expression.end_col_offset]])
        return raw.decode("utf-8")[:200]

    def run(self) -> None:
        # Conservatively invalidate explicit monkey patches before resolving
        # calls, independent of statement ordering or conditional execution.
        for path, tree in self.trees.items():
            _Walker(self, path, collect_mutations=True).visit(tree)
        for path, tree in self.trees.items():
            _Walker(self, path).visit(tree)


class _Walker(_IterativeGenericVisitor):
    def __init__(self, extractor: _Extractor, path: str, collect_mutations: bool = False) -> None:
        self.extractor, self.path = extractor, path
        self.scope = extractor.paths[path]
        self.source_id = self.scope.node_id
        self.collect_mutations = collect_mutations

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for value in [*node.decorator_list, *node.args.defaults,
                      *[x for x in node.args.kw_defaults if x is not None],
                      *[arg.annotation for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                        if arg.annotation is not None],
                      *([node.returns] if node.returns is not None else [])]:
            self.visit(value)
        self._body(node, self.extractor.scopes[id(node)])

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for value in [*node.bases, *node.decorator_list, *[x.value for x in node.keywords]]:
            self.visit(value)
        self._body(node, self.extractor.scopes[id(node)])

    def _body(self, node: Any, scope: _Scope) -> None:
        old_scope, old_source = self.scope, self.source_id
        self.scope, self.source_id = scope, scope.node_id
        for statement in node.body:
            self.visit(statement)
        self.scope, self.source_id = old_scope, old_source

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for value in [*node.args.defaults, *[x for x in node.args.kw_defaults if x is not None]]:
            self.visit(value)
        old_scope = self.scope
        scope = _Scope(self.source_id, "lambda", old_scope.module, old_scope)
        args = node.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs,
                    *([args.vararg] if args.vararg else []), *([args.kwarg] if args.kwarg else [])]:
            scope.bind(arg.arg, ("unknown", "lambda_parameter"))
        _Bindings(scope, self.extractor).visit(node.body)
        self.scope = scope
        self.visit(node.body)
        self.scope = old_scope

    def _comprehension(self, node: Any) -> None:
        old_scope = self.scope
        # The first iterable is evaluated outside the implicit comprehension.
        self.visit(node.generators[0].iter)
        scope = _Scope(self.source_id, "comprehension", old_scope.module, old_scope)
        for generator in node.generators:
            for child in ast.walk(generator.target):
                if isinstance(child, ast.Name):
                    scope.bind(child.id, ("unknown", "comprehension_binding"))
        self.scope = scope
        for index, generator in enumerate(node.generators):
            if index:
                self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self.scope = old_scope

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self.collect_mutations and isinstance(node.ctx, (ast.Store, ast.Del)):
            base, _ = self.extractor.resolve(node.value, self.scope)
            if base is not None:
                self.extractor.invalid_attributes.add((base[1], node.attr))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self.collect_mutations:
            if (isinstance(node.func, ast.Name) and node.func.id in {"setattr", "delattr"}
                    and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                base, _ = self.extractor.resolve(node.args[0], self.scope)
                if base is not None:
                    self.extractor.invalid_attributes.add((base[1], node.args[1].value))
        else:
            target, reason = self.extractor.resolve(node.func, self.scope)
            expression = self.extractor.expression_text(self.path, node.func)
            if target is not None and target[0] == "node" and self.extractor.nodes[target[1]]["kind"] in {"function", "class"}:
                edge = {"source": self.source_id, "target": target[1], "type": "calls",
                        "path": self.path, "line": node.lineno, "expression": expression,
                        "resolution": "supported"}
                edge["id"] = edge_identifier(edge)
                self.extractor.edges.append(edge)
            else:
                self.extractor.unknown.append({"source": self.source_id, "path": self.path,
                                               "line": node.lineno, "expression": expression,
                                               "reason": reason if target is None else "non_callable_binding"})
        self.generic_visit(node)


def build_graph(root: Path | str, commit: str = "unknown") -> dict[str, Any]:
    """Build a source-supported graph with stable order, IDs and provenance.

    Reads Python source only. Parse/decode/read failures are returned in
    ``errors`` rather than silently removing evidence. Symlink files are skipped
    so the snapshot cannot accidentally include source outside ``root``.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Graph source root is not a directory: {root}")
    sources: dict[str, str] = {}
    files: list[dict[str, str]] = []
    errors: list[dict[str, Any]] = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in _IGNORED and
                         not Path(directory, name).is_symlink())
        for name in sorted(names):
            if not name.endswith(".py"):
                continue
            full_path = Path(directory, name)
            path = full_path.relative_to(root).as_posix()
            if full_path.is_symlink():
                errors.append({"path": path, "line": None, "error": "symlink_ignored"})
                continue
            try:
                raw = full_path.read_bytes()
            except OSError as exc:
                errors.append({"path": path, "line": None, "error": "read_error", "message": str(exc)})
                continue
            files.append({"path": path, "sha256": _hash(raw)})
            try:
                encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
                sources[path] = raw.decode(encoding)
            except (SyntaxError, UnicodeDecodeError, LookupError) as exc:
                errors.append({"path": path, "line": None, "error": "decode_error", "message": str(exc)})
    extractor = _Extractor(sources)
    extractor.initialize()
    extractor.run()
    files.sort(key=lambda item: item["path"])
    snapshot_hash = _hash(json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    # Repeated identical calls on one physical line share their relationship ID.
    # This is a relation graph, not an event trace; retain each relationship once.
    edges = {edge["id"]: edge for edge in extractor.edges}
    unknown = {json.dumps(item, sort_keys=True): item for item in extractor.unknown}
    return {"schema_version": 1,
            "snapshot": {"commit": commit, "source_sha256": snapshot_hash, "files": files},
            "nodes": sorted(extractor.nodes.values(), key=lambda item: item["id"]),
            "edges": sorted(edges.values(), key=lambda item: item["id"]),
            "unknown": sorted(unknown.values(), key=lambda item: (item["path"], item["line"], item["expression"], item["source"])),
            "errors": sorted([*errors, *extractor.errors], key=lambda item: (item["path"], item.get("line") or 0, item["error"]))}
