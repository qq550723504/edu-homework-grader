# AI Generation Evaluation Design — Superseded

**Status:** Superseded on 2026-07-23  
**Authoritative design:** [AI Question Evaluation Design](2026-07-23-ai-evaluation-design.md)

This document described a broader evaluator that rebuilt candidate inputs, reran production verification, required human-review attestations, compared baselines, and added online reporting in one delivery.

The implementation is intentionally split into separate, reviewable boundaries:

1. **#83 deterministic verification corpus** reruns the current production candidate verifier against M1, M2, E1, E2, E3, and E4 regression cases, including dependency failures and malicious inputs.
2. **#42 offline evaluation gate foundation** evaluates de-identified, teacher-adjudicated snapshots, enforces minimum evidence and cross-field consistency, applies versioned thresholds, and emits JSON/HTML release evidence.
3. **#42 follow-up work** remains responsible for operational exports, teacher-feedback summaries, baseline comparison, online metrics, and final release-threshold calibration.
4. **#43** owns model/Prompt promotion, shadow/canary routing, rollback, budget controls, and kill switches.
5. **#31** owns release-environment end-to-end acceptance.

The offline evaluator does not call a model provider, read a production database, or promote a model or Prompt. A passing report is necessary release evidence, not sufficient production approval.
