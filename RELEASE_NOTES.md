# Implementation preview: v0.1.0-alpha.2

This preview provides the GraphTrust-SWE software resource: conservative Python
relationship extraction, deterministic deletion/rewiring, fixed source contexts,
a source-consistency baseline, resumable inference logs, paired metrics, and
reproduction tools. The wheel's package version remains 0.1.0; the Git
tag identifies an implementation preview.

This revision makes the test suite work from a clean source download by creating
its own temporary wheel fixture. It removes a dependency on an unpublished local
build artifact; the core package and inference behavior are unchanged.

There are no empirical Gemma robustness findings in this release. Synthetic
examples exercise the software and are labeled synthetic. A passing real
development pilot, protocol freeze, primary study, replication, paper results,
and competition submission remain pending. The methods draft is a research
template, not a completed competition paper.

The original code and synthetic fixtures use Apache 2.0. Upstream dataset,
repository, and model assets retain their original terms. The release contains
regeneration identifiers and hashes rather than benchmark patches, evaluator
tests, repository source packs, or model/tokenizer weights. The manual audit
quotes short attributed source fragments; it does not relicense upstream code.

From a source checkout or extracted source archive:

```text
python -m pip install .
python -m graphtrust demo --out runs/demo
python -m graphtrust validate --directory runs/demo
python -m unittest discover -s tests -v
```

The core runtime needs only Python 3.11+ and the standard library. Initial source
installation needs the declared build backend. A wheel can be installed without
build dependencies using `python -m pip install --no-deps <release-wheel.whl>`.
The installed demo requires no model, corpus download, hosted API, or GPU.
Plots and corpus acquisition use optional package extras. Both included notebooks
have cleared outputs; the Kaggle notebook defaults to no real inference.

See [reproduction instructions](docs/REPRODUCIBILITY.md), the
[resource card](docs/RESOURCE_CARD.md), and
[release checklist](docs/RELEASE_READINESS.md). Development evidence paths under
ignored `runs/`, `data/`, and `models/` identify private artifacts or regeneration
outputs; reproduction uses the public commands and tools in this repository.
