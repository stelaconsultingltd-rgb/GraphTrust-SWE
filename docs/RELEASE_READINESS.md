# Implementation release checklist

The historical artifact audit below describes the alpha.2 software preview,
which is now [public](https://github.com/stelaconsultingltd-rgb/GraphTrust-SWE/releases/tag/v0.1.0-alpha.2).
The current prospective package 0.3.0 separately passed author and independent
212-test suites and an installed-wheel offline demo. Its reviewed implementation
fingerprint is `cc558cf01c545cedbba04b568da2d451613353a2d742c913f8535c21b24be246`.
Fresh final corpus preparation and a matching real pilot remain pending. These
software checks do not establish a final scientific freeze or empirical release;
see [execution status](EXECUTION_STATUS.md).

## Historical software-preview audit

Audit date: 10 October 2026. The proposed `v0.1.0-alpha.1` release is an
implementation preview. It must not claim a completed scientific study, a frozen
protocol, or Gemma findings. No public repository/tag has been created by this
reviewer.

## Checked artifact boundaries

- The wheel contains original package code, synthetic fixtures, the development
  protocol, license, notice, and package metadata. No evaluator, corpus archive,
  graph/source pack, model, or tokenizer assets are included.
- The source-distribution manifest includes public configs, scripts, notebooks,
  docs, fixtures, tests, license, and notice; it explicitly excludes private
  handoffs, caches, raw inputs, runs, models, virtual environments, and build outputs.
- The dataset manifest contains 323 identifiers/hash records with seven allowed
  fields per case. It contains no issue text, patch, added test, or reference-edit
  labels. The dataset lock includes evaluator file hashes, not their contents.
- The inspected public candidate files had no static matches for credential
  tokens, signed/authenticated URLs, or absolute machine paths. Both notebook
  files have zero saved outputs and zero execution counts. This pattern scan is
  a bounded check, not proof that arbitrary future additions contain no secrets.
- The observed local requirements inventory is explicitly labeled and normalized
  to `-e .`; it is not a hashed CUDA installation lock. Public preflight commands
  use the shipped `graphtrust validate` tool. Ignored audit helpers are evidence
  references, not installation prerequisites.
- A separate source archive installed offline to a fresh target outside the
  checkout. Its installed-package demo produced six contexts and twelve synthetic
  attempts with identical source, then passed manifest validation. All four
  public script help commands worked from its source tree. Both notebooks' code
  cells compiled; no model inference was run during this check.

The reviewed implementation SHA-256 is
`bc084db6c4922dda6c05ed69e8709103e3db659526352596d8db28538d0697ae`.
The canonical protocol SHA-256 is
`f12e3788aff29530923d70b2af732ed8d63a43125aa171168579bc6bd5166dff`.
The preserved wheel SHA-256 is
`c492f95f679792c81e9063d73825179dcab686e5bfadb1a63f05b8e256c77b71`.
Detailed development inventories, archive hashes, command logs, and scan evidence
are retained privately under `runs/release-audit/`. The public reproduction does
not require that directory.

## Explicit public staging scope

Stage the following roots deliberately, after reviewing their contents:

```text
.gitattributes .gitignore AGENTS.md LICENSE NOTICE MANIFEST.in
README.md RELEASE_NOTES.md pyproject.toml requirements-local.lock.txt
configs/ docs/ fixtures/ notebooks/ scripts/ src/graphtrust/ tests/
```

Exclude `.agent-handoff/`, `.git/`, `.venv/`, `data/`, `runs/`, `models/`,
`build/`, `dist/`, egg-info, bytecode, and logs from the Git source tree.
Attach only individually inspected wheel/source archives as release downloads;
do not upload a workspace archive. Re-run the bounded scan and archive inventory
against the final staged set if that set changes.

To build a source artifact in a separate output directory:

```text
python -m pip install build
python -m build --sdist --outdir runs/release-sdist
```

The build uses the declared isolated setuptools backend. Do not use
`--no-isolation` unless that backend is already installed. Inspect the tar archive
before publication and record its actual SHA-256 with the release. Source-archive
bytes include build metadata/timestamps; matching the implementation/protocol
fingerprints is distinct from recreating an identical tarball.

## Remaining work before the implementation preview is public

1. Commit the reviewed allowlist, create the intended public repository and tag,
   and attach the reviewed wheel/source archive plus checksums. Keep the proposed
   tag wording and release notes explicit about implementation-only status.
2. Test the resulting public checkout/download links, wheel install, default
   notebook/demo instructions, and manifest recipe from those public assets.
   Supply the resulting URLs in the resource card and competition draft later.
3. Retain the Apache license and original-code notice; preserve attribution and
   applicable upstream notices for any future distributed third-party examples.
   Regenerate restricted or upstream assets instead of bundling private inputs.

## Remaining scientific release work

The current real pilot must pass all gates before freezing. Recover acquisition
errors independently of structural qualification, complete the CPU corpus and
diagnostics, and disclose all shortfalls. Finish the primary experiment before
optional work. Model records must preserve failures and full run denominators.

Before releasing empirical results, create and audit an explicit public result
export containing permitted response records, metadata-only contexts, manifests,
and reports. Exclude raw prompts/source packs, patches, evaluator tests, gold
labels, credentials, and signed URLs; regenerate evaluator inputs for independent
scoring. The prospective `graphtrust export` implementation and its boundary tests
are documented in [PUBLIC_RESULTS_EXPORT.md](PUBLIC_RESULTS_EXPORT.md). No actual
empirical cohort has been exported or accepted by these software tests. There is
no empirical evidence in this implementation preview.
Complete negative or positive results must be reported without selective removal.

Only then replace paper placeholders with traceable tables/figures, review claims
and reproduction independently, verify the official submission requirements, and
confirm the Kaggle Writeup is actually submitted. A development tag is not a
competition submission.
