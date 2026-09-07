# Results20 provisional cost estimate — 2026-09-05 12:00 CST

Planning estimate for the 240-assignment, 5–10-revision experiment including three-provider audits: **USD 1,500–3,500**, not a cap, guarantee, or invoice. The user explicitly confirmed that budget is not a blocker. No model, scientific protocol, or running source was changed for this estimate.

## Evidence and extrapolation

- Repriced persisted, response-ID-deduplicated audit usage: v3 **$15.4763** (165 recorded API responses for 153 semantic judgments), v4 **$15.8282** (175 recorded API responses for 162 semantic judgments). Chunked trajectory checks explain why response counts exceed judgment counts. These were each one development task × one selected replicate × four arms × three revisions, not Results20 outcomes.
- V4 audit alone at 60 times the number of assignments would be approximately **$950** at the same task/trajectory size. Allow roughly 1.5–3 times that audit workload for the full 5–10-turn protocol, plus generation/proposal/feedback work and task variability, producing the broad planning range above. This is a heuristic from one task, not a statistical confidence interval; long traces, retries, and task heterogeneity can move the total outside it.
- At approximately 12:00 CST, 110 available Results20 seed/adversarial terminal streams had a combined Luna token-price estimate of **$1.801744**; unfinished streams, initial grading, paraphrases and other calls are excluded. This is a partial recorded amount, not total expenditure.
- The two v5 targeted proposer regressions recorded 10 calls totaling **$0.083256** under the local Luna estimator. Historical proposer retries/interrupted stages do not have a complete durable per-call usage ledger, so total historical spending cannot be reconstructed exactly from these artifacts.

## Rate assumptions checked today

USD per million input/output tokens: Luna 0.20/1.20, Sol 4/20, Claude Opus 5 5/25, Gemini 3.8 Flash 0.75/3.75. OpenAI/Anthropic recorded cache reads and writes are accounted for; Gemini input is conservatively charged at the uncached introductory rate. OpenAI requests exceeding 272K input tokens would need the long-context adjustment; this sample's chunked audit requests stay below that threshold. Provider invoices, negotiated discounts, failed requests without persisted usage, and Codex subscription accounting are not available here.

Sources: [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Gemini 3.8 introductory pricing](https://ai.google.dev/gemini-api/docs/latest-model?hl=en).

The frozen runtime price registry still uses Sol 5/30 and has no Gemini 3.8 entry. Its aggregate cost fields therefore do not represent a complete, current bill. This separate estimate leaves all original artifacts and the running implementation unchanged; final cost reporting must recompute from usage and clearly identify missing coverage.

## Status at 12:00 CST

Formal preparation is running: 60/60 ordinary solutions exist, 51/60 complete seed blocks are sealed, and 100/100 paraphrases are complete. The 240 formal revision assignments and their final audits have not started yet. Previous v1–v5 runs were integration/reliability checks and remain separate from the Results20 result namespace.
