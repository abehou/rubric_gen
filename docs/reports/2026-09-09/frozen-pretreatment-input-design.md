# Explicit frozen pretreatment input: implementation requirements

Scope: the user explicitly requires reuse of the realized cue starting rubrics across a new online policy implementation. This is consumption of immutable current-format scientific input, not resume compatibility or a claim that current code generated it.

1. Keep ordinary generation/resume identity checks strict. Do not modify elicit_rubric to silently accept different producers.
2. Add an explicit read-only frozen-pretreatment input validator, used only for configured pretreatment_source. It must require offline generation1, source_checkpoint=None, the expected selected/development rubrics, seed/task/model/protocol context, and a completed source study.
3. Revalidate every current-format generation file/hash, artifact history, assessment, proposal, criterion application, admission decision and rendered rubric using native offline semantics. If semantic replay differs, reject. Never call a provider from this input validator; missing data is an error.
4. Compare the source's producer identity as original provenance, not against consumer implementation identity. Do not overwrite it or an old cache key. Pin the source generation/evolution digest in a new consumer verification receipt alongside current consumer identity and source experiment identity.
5. Validate the installed copy byte-for-byte against the verified source. Resume must recheck the same source digest and receipt; it must not broaden acceptance to arbitrary historical/obsolete formats.
6. Negative tests must cover edited source, wrong task/seed/rubric/model context, online generation supplied as pretreatment, changed admission, incomplete source, and provider-call attempts. A matching source must preserve exact criterion IDs/levels/order and starting rubric hashes.

The current no-provider completed-generation loader already reconstructs most semantic evidence and rejects a different producer at the final metadata comparison. Prefer a dedicated explicit-input validation path sharing that reconstruction over a second parser, identity monkeypatch, global override, or arbitrary compatibility exemption. This design is not implemented or launch approval evidence.

## Implementation checkpoint

RubricProposer.validate_frozen_pretreatment_input now requires a pinned source evolution digest, preserves its original producer identity, and reuses complete native offline evidence/admission/rendered-generation reconstruction. It cannot generate missing work. Ordinary elicit/resume retains current-producer equality.94related tests pass; explicit success verifies byte-identical source and no provider call while wrong source digest/task fail. Study integration, consumer receipt pinning, expanded negative cases and real cue source validation remain pending. This is not launch-ready evidence.
