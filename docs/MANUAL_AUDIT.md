# Manual source and intervention audit

Audited 10 October 2026. This is a small, purposive inspection of cached source
and constructed metadata, not a measurement of model behavior or graph accuracy.
No evaluator patches, added verification tests, or reference-edit labels were
opened or used. Repository source was read as text and parsed without executing
the upstream projects.

## Source artifacts inspected

The two records come from `runs/dev-cpu-v4/audit.jsonl`. Their recorded
implementation fingerprint is
`5573a4a77b8487d5a20401a82707a0090ceec0d8e94fe2138b996e2fcca83613`,
and their extractor fingerprint is
`7051e09a5c729ed75ee1baa7d84db320fa961c7c10de89efe46473c346bcc4c4`.
These identifiers describe the inspected artifacts; they do not certify that an
older preparation is usable with a later implementation. In particular, the
packed-graph rewire issue described in `SCIENTIFIC_REVIEW.md` was subsequently
fixed. This clean-source audit does not validate every old intervention.

| Field | pvlib | astroid |
| --- | --- | --- |
| Case | `pvlib__pvlib-python-1072` | `pylint-dev__astroid-1196` |
| Repository | `pvlib/pvlib-python` | `pylint-dev/astroid` |
| Base commit | `04a523fafbd61bc2e49420963b84ed8e2bd1b3cf` | `39c2a9805970ca57093d32bbaf0e6a63e05041d8` |
| Graph artifact under `runs/dev-cpu-v4` | `graphs/99dfbed7b38956093184317374b40ce5c1f48303b21b1a0ee4d39a11291fe8a2.json.gz` | `graphs/c8f887271ff427ae17d9289a19848e9ee06d7f88f3e0104eb35c1ea0cf003356.json.gz` |
| Compressed graph SHA-256 | `129618b0cbe1e433f4e98128594f22bf54c57de14231140852077e64f8f50867` | `7a30f48cd4c05031ad3c705a2f55213e8b9e1c40db094bfae6c6417a4f8f187a` |
| Source snapshot SHA-256 | `091f601e667bcfdbfd570f1ad11e9707f189ffe2395f524b88d17e819194e9a8` | `4759f4ac2ce14549779eaebae26360610bcf4b08fa4a91bfa7d4ed81d5771ed7` |
| Downloaded archive SHA-256 | `6c5da7a116f3a7e275feb1d9cc7fec00e74837e3e89190d21730f24105068bb0` | `46831a597931a096985462350a31f55e9b8b84c4f99efdfd8d0a73ae0c41e770` |
| Graph nodes / supported edges / unknown bindings | 1,331 / 786 / 6,502 | 3,382 / 2,619 / 11,094 |

Cached snapshots are located at
`data/swebench-lite/cache/snapshots/<repository with / replaced by __>-<commit>/`.
All 98 pvlib and 221 astroid graph file hashes were recomputed from cached raw
bytes and matched both the graph file list and the snapshot marker. The source
snapshot hash was recomputed from the canonical JSON file list. Both compressed
graph hashes matched the audit records. For each of the ten selected edges, the
caller and target node slices matched the cached decoded line ranges exactly,
and the stored node SHA-256 values matched their UTF-8 text.

## Ten inspected source-supported relationships

Selection sought a mixture of same-module helpers, imported names, a module
attribute, a class construction, a package re-export, and a nested function.
It was not sampled to estimate a population error rate. The call expression at
each recorded line was also checked against its Python AST. None of the called
root names was a caller parameter or an assignment/deletion target in the
inspected caller body. The table quotes only short evidence fragments; full
upstream source must be regenerated under its original license.

| Edge ID | Recorded caller and exact call line | Target definition and binding evidence |
| --- | --- | --- |
| `e_00b48c00a0eaeda32669b3dc` | `pvlib/tracking.py::SingleAxisTracker.localize`, line 142: `location = Location(latitude, longitude, **kwargs)` | `pvlib/location.py::Location`, line 17: `class Location:`. Imported by `from pvlib.location import Location` at tracking line 7. |
| `e_045994d435bee6a2865578ea` | `pvlib/clearsky.py::simplified_solis`, line 471: `g = _calc_g(w, aod700)` | `pvlib/clearsky.py::_calc_g`, line 540: `def _calc_g(w, aod700):`. Same-module name. |
| `e_044b3f6f84d40bedb3a7bb09` | `pvlib/tracking.py::_calc_tracker_norm`, line 600: `sin_bg = sind(bg)` | `pvlib/tools.py::sind`, line 30: `def sind(angle):`. Tracking line 4 imports `cosd, sind, tand` from `pvlib.tools`. |
| `e_0b117a2102f97a0bc3662542` | `pvlib/inverter.py::fit_sandia`, line 413: `b_s0, b_s1, c2 = extract_c(x_d, coeffs['p_s0'])` | `pvlib/inverter.py::fit_sandia.extract_c`, line 391: `def extract_c(x_d, add):`. Nested definition precedes this call. |
| `e_0c4a9e8125a39454952b1102` | `pvlib/iotools/tmy.py::read_tmy2`, line 388: `tmy2, tmy2_meta = _read_tmy2(string, columns, hdr_columns, str(filename))` | `pvlib/iotools/tmy.py::_read_tmy2`, line 427: `def _read_tmy2(string, columns, hdr_columns, fname):`. Same-module name. |
| `e_02d770359c5631d4abb2a4ad` | `astroid/filter_statements.py::_filter_stmts`, line 138: `if_parent = _get_if_statement_ancestor(assign_type)` | `astroid/filter_statements.py::_get_if_statement_ancestor`, line 34: `def _get_if_statement_ancestor(node: nodes.NodeNG) -> nodes.If \| None:`. Same-module name. |
| `e_0091922605b11958899babe3` | `astroid/bases.py::Instance.getitem`, line 327: `new_context.callcontext = CallContext(args=[index], callee=method)` | `astroid/context.py::CallContext`, line 156: `class CallContext:`. Imported from `astroid.context` in the multiline import beginning at bases line 13. |
| `e_054b36bb36c65ea0aa3d4340` | `astroid/protocols.py::tl_infer_binary_op`, line 194: `as_index = helpers.class_instance_as_index(other)` | `astroid/helpers.py::class_instance_as_index`, line 204: `def class_instance_as_index(node):`. Protocols line 17 imports the `helpers` module from `astroid`. |
| `e_0419bf049c0fe269a16b56a8` | `astroid/brain/brain_typing.py::infer_typing_attr`, line 167: `func_to_add = _extract_single_node(CLASS_GETITEM_TEMPLATE)` | `astroid/builder.py::_extract_single_node`, line 444: `def _extract_single_node(code: str, module_name: str = "") -> NodeNG:`. Direct import from `astroid.builder` at brain_typing line 14. |
| `e_05658fcb14d75d201bfd3ade` | `astroid/brain/brain_ssl.py::ssl_transform`, line 13 begins `return parse(` | `astroid/builder.py::parse`, line 268: `def parse(code, module_name="", path=None, apply_transforms=True):`. Brain_ssl line 7 imports `parse` from `astroid`; `astroid/__init__.py` line 50 re-exports it from `astroid.builder`. |

The inspected source-file byte hashes provide a compact cross-check independent
of the graph's node text:

| Cached path | SHA-256 |
| --- | --- |
| `pvlib/tracking.py` | `885e5de433e0b0db38a60cebf3486a1818dd4d609fc5c60402ca7f0774f56f2b` |
| `pvlib/location.py` | `e2d299a9c5bd90bdcd085739db5fb36108d125c3941efcd90ebb6003ffe3d64e` |
| `pvlib/clearsky.py` | `f83fe7dc9af3b76064e0c019283337f0d6872c63d2ce2d4164bc826fd667ebfe` |
| `pvlib/tools.py` | `8f10dbcc4f6ab6c7c208b97efe86ccaa1f7e7a4e591309eb6f4c8237fcc82d5e` |
| `pvlib/inverter.py` | `22cea45d86a34e0b8e466989db0e67320be436ed1f76fa0e9b9967aa049d13c7` |
| `pvlib/iotools/tmy.py` | `3cfa7960e6d255ff6afb1a48b726c5eaeb5ad830cecce2c2f98b18e1a35104fc` |
| `astroid/filter_statements.py` | `72864b51ea51236aec712222c989c9dc2c8f8daec46fcad37b8fb6ff77d4a4fa` |
| `astroid/bases.py` | `456cd114ccb3264839098a70b916b48368ca402919e92078f7db3b5e487211e1` |
| `astroid/context.py` | `fd0985ce3e33ea70ba8616a0e2168227eb8c1d94f38d94368342675c5b2dfe01` |
| `astroid/protocols.py` | `dd205c306ef7589712c32010cea1ede28c4820442e37ab0b0007fa7f145b773c` |
| `astroid/helpers.py` | `85c0173f5d42ddaec9d23c0e62e7700874e06a3abb45c4403d31e62a972acd2c` |
| `astroid/brain/brain_typing.py` | `edb5873788d76dd86865173006a574aee920feec301627d7a0b33a5d4d63e7ee` |
| `astroid/builder.py` | `0a8e726d4af79511bde352c9bf5985acbc4341f03be8c76ab61f2b56a946cefb` |
| `astroid/brain/brain_ssl.py` | `8144ddce8515940f1e86dc028f2277a3aa261b53eaa013ecd9c5c30c39862373` |
| `astroid/__init__.py` | `e14e89529fe350c38668f772c23b0d31b44943b78c49802650a1bae7d5dd1acd` |

Finding: all ten inspected edges have the declared static source evidence. This
does not establish runtime dispatch, successful imports, graph completeness, or
visibility of those lines in a model's truncated source pack. Astroid explicitly
records one decode error at `tests/testdata/python3/data/invalid_encoding.py`
(`unknown encoding: lala`); it was not silently treated as parsed source. The
large unknown-binding counts above remain unresolved, and test code is included
in extraction even though production source packing filters test files.

## Concrete synthetic interventions

Inspected saved artifacts: `runs/demo-v3/graph.json.gz`,
`runs/demo-v3/qualification.json`, and `runs/demo-v3/contexts.jsonl` for
`synthetic-whitespace`. The gzip graph SHA-256 is
`9b1c8f25a6ca479179bad36f2fa46e6356f792d322379f2ef82fd234b1f76dd4`;
qualification SHA-256 is
`9e5bb18ebc941b806d68f3ebcb753f80d5f5e19a53e891c9e7bd53910548c6a7`;
contexts SHA-256 is
`f188efefa64fa03e8b3804e912c12866d865b6ec7b26db83898a8eeff93626ef`.

The common packed baseline has 9 edges and canonical JSON SHA-256
`ff5fac45a58954e23a003d1c1ab83aa34aed0cd3453892b341b0bada0f7c7edf`.
At seed 1729, nominal severity 0.3 requests 3 changed edges, but paired endpoint
swaps achieve 2 (2/9 = 22.22%), with an explicit one-edge parity shortfall.
The rewire retains 9 edges and has SHA-256
`112105a96a1671c7e506ae64dd3dc4217d0af00787887cba097648f4a3e74dcd`.
The matched deletion removes 2 edges, leaves 7, and has SHA-256
`12387beb592fd6bc30fa704652ddc78e503c40f80ad1bddca648ba8072a184d0`.

| Replacement ID | Retained source call site | Claimed replacement target | Source-derived target |
| --- | --- | --- | --- |
| `e_dda18ec39d6a681bae2ed7ec` | `display.py::display`, line 4, `format_value` | `validate.py::validate` | `formatting.py::format_value` |
| `e_eabafd530fd48d0f102684fb` | `normalize.py::normalize`, line 4, `validate` | `formatting.py::format_value` | `validate.py::validate` |

The actual source lines are `return format_value(value)` and `validate(value)`.
Both replacement endpoint relationships are absent from the **full** synthetic
source graph, rather than merely absent from its packed metadata. The checker
classifies both as `contradicted` at their preserved call sites and the other
7 relationships as `supported`. These are static classifications; the retained
`resolution` field describes the supplied relationship claim, not corroboration
of corrupted metadata.

Deleted relationship IDs are `e_01277b740268b7f9a3005b50` and
`e_c6064063210eb487d81d9d4f`. Rewired and deleted graphs preserve the baseline
nodes, snapshot, and unknown fields exactly. The literal source-pack substring
is byte-identical in all six saved conditions, with SHA-256
`e8f5e54ea0301d2c563b41438bad0d92256f8a17f26fd6b022711dfcce3a115c`.
This is a synthetic CPU demonstration using `byte_upper_bound` budgeting; it is
not evidence of an exact Gemma-tokenized pilot or a frozen scientific study.

The saved sidecars were reproduced exactly after the integrity fix by supplying
the full synthetic graph as `source_graph`. The separate scientific-review
counterexample is covered by `test_packed_graph_cannot_rewire_into_omitted_source_supported_relation`:
an otherwise valid relation omitted from packed metadata blocks the swap when
full-source support is supplied. Existing pre-fix artifacts must not inherit
this stronger guarantee without regeneration or an explicit full-source audit.

## Reproduce the synthetic checks

From the repository root after installation, run this Python snippet. The
snapshot/file checks described above additionally require the regenerated
development cache, which is not bundled in the original-code release.

```python
import gzip
import hashlib
import json
from pathlib import Path
from graphtrust.interventions import check_edges, perturb_graph

p = Path("runs/demo-v3")
g = json.loads(gzip.decompress((p / "graph.json.gz").read_bytes()))
q = json.loads((p / "qualification.json").read_text())
rows = [json.loads(line) for line in (p / "contexts.jsonl").read_text().splitlines()]
clean = next(row for row in rows if row["condition"] == "clean")
node_ids, edge_ids = set(clean["visible_source_ids"]), set(clean["visible_edge_ids"])
packed = {**g, "nodes": [n for n in g["nodes"] if n["id"] in node_ids],
          "unknown": [], "edges": sorted(
              [e for e in g["edges"] if e["id"] in edge_ids], key=lambda e: e["id"])}
rewired, rs = perturb_graph(packed, "rewire", 0.3, 1729, source_graph=g)
deleted, ds = perturb_graph(packed, "delete", 2 / 9, 1729, source_graph=g)
assert rs == q["rewiring"] and ds == q["deletion"]
for field in ("nodes", "snapshot", "unknown"):
    assert rewired[field] == deleted[field] == packed[field]
supported = {(e["source"], e["target"], e["type"]) for e in g["edges"]}
verdicts = check_edges(rewired, g)
for edge in rewired["edges"]:
    if edge["id"] in rs["false_edge_ids"]:
        assert (edge["source"], edge["target"], edge["type"]) not in supported
        assert verdicts[edge["id"]] == "contradicted"
packs = [row["prompt"].split("\nSOURCE PACK\n", 1)[1]
         .split("END SOURCE PACK\n", 1)[0] for row in rows]
assert len(set(packs)) == 1
assert hashlib.sha256(packs[0].encode()).hexdigest() == clean["source_sha256"]
print("Synthetic intervention counts, provenance, and source invariance verified.")
```

## Final v8 shared-excerpt inspection

After the single development-only callsite packing revision, three constructed
false edges were inspected in `runs/pilot-tokenized-v8/contexts.jsonl` against
their actual cached source lines and full source graphs from `runs/dev-cpu-v8`.
Selection used the first recorded swap in three selected pilot cases, spanning
three repositories; no gold information or model outcomes were inspected.
The implementation SHA-256 is
`bc084db6c4922dda6c05ed69e8709103e3db659526352596d8db28538d0697ae`
and the protocol SHA-256 is
`f12e3788aff29530923d70b2af732ed8d63a43125aa171168579bc6bd5166dff`.
Machine-readable evidence, including caller-file hashes, original edge IDs,
checked context hashes, and source hashes, is saved in
`runs/pilot-tokenized-v8/MANUAL_FALSE_EDGE_AUDIT.json`.

| Case and false edge | Exact visible original call line | Claimed target versus source-derived target | Missing binding/definition evidence in the shared pack |
| --- | --- | --- | --- |
| `sqlfluff__sqlfluff-1517`, `e_b1d638a4c805482c23b76df3` | `src/sqlfluff/cli/commands.py:674`: `lnt, formatter = get_linter_and_formatter(c, silent=non_human_output)` | `src/sqlfluff/core/parser/match_wrapper.py::match_wrapper` replaces the same-module `get_linter_and_formatter` | Correct definition at commands line 205 and replacement definition at match_wrapper line 28 are both absent. No import alias is involved in the original same-module binding. |
| `pylint-dev__astroid-1268`, `e_7e34cfd97665a9aa9fc3b0be` | `astroid/brain/brain_subprocess.py:136`: `register_module_extender(AstroidManager(), "subprocess", _subprocess_transform)` | `astroid/interpreter/objectmodel.py::ModuleModel` replaces `astroid/manager.py::AstroidManager` | Direct import `from astroid.manager import AstroidManager` at caller line 21 is absent; no renamed alias is used. Correct class definition at manager line 64 and replacement class definition at objectmodel line 131 are absent. |
| `pvlib__pvlib-python-1707`, `e_d597f04af8b4630d5ff130f2` | `pvlib/iotools/psm3.py:227`: `return parse_psm3(fbuf, map_variables)` | `pvlib/iotools/epw.py::parse_epw` replaces the same-module `parse_psm3` | Correct definition at psm3 line 230 and replacement definition at epw line 240 are absent. No import alias is involved in the original same-module binding. |

Each call-line string matched the actual shared excerpt exactly. All three
replacement relationships are absent from the corresponding **full** source
graph, and all three checked contexts label them `contradicted`. Their visible
call spellings give a lexical mismatch with the supplied target names, but this
inspection does not establish complete binding or runtime dispatch from the
excerpts alone. In particular, the missing astroid import line prevents the
model from seeing that binding directly. The source checker has the complete
same-commit snapshot; it is an integrity baseline with greater source access
than the localization model, whose shared excerpts remain fixed.

| Case | Rewired context SHA-256 |
| --- | --- |
| `sqlfluff__sqlfluff-1517` | `b79b1e502ab1dfa15df654b2d0eae5130105c2dfd5f6f30faaac5595c0f82d7f` |
| `pylint-dev__astroid-1268` | `3c191aaf727b1368ff91acca908fa4cad45ce0f41007c99c8974ba436e8ad485` |
| `pvlib__pvlib-python-1707` | `807b9f03a397b15596644a1591ba3a5d699277bcedc2440577f045b80078aa5a` |

The v8 CPU context audit verifies 73/73 retained clean callsites and 20/20 false
callsites visible across the ten pilot issues, with identical source bytes in
all six conditions. Those counts describe constructed context coverage and do
not establish graph accuracy, model behavior, or experimental findings.
