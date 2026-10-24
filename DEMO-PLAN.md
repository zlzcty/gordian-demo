# Modular demo plan

1. Add `baseline`, `generate`, `assisted`, and `check` modes to the existing entry point. Preserve the old combined flow for compatibility.
2. Describe the target in JSON: driver, replaceable fragment, helper sources, compiler flags, model instructions, symbolic input contract, replay format, and required outcomes. Snapshot code and settings once at baseline; later stages consume that snapshot rather than mutable checkout files. Initially support one bounded little-endian binary64 input and an integer outcome; document that boundary.
3. Separate target/evidence transformations, model transport, compilation/execution, artifact handling, and stage orchestration. Keep orchestration functions at one abstraction level. Generate independently of Docker; execute independently of provider credentials. Refuse artifact overwrites and preserve failed stages.
4. Check Python packages, Docker, running container, mount, executable tools, target files/settings, output access, and endpoint/model/key settings using simple `Name: OK/FAIL` lines. Probe model access without a completion using an explicit option; otherwise settings checks make no claim of model availability.
5. Add meaningful stage-transition and replay-evidence tests, update the tutorial, then start the existing official Docker container and rehearse all three stages with the explicitly labeled mock. Print SUCCESS only when assisted original-code replay covers all required target outcomes. Do not infer range equivalence from witnesses.

Completed: all four modes, target descriptor and frozen artifacts, readiness script, updated tutorial, 80 passing tests, complete real-KLEE/mock-model rehearsal, and an alternate-target baseline check. See DEMO-NOTES.md for measured results.
