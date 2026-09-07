# Gemini access investigation — 2026-09-06

## Follow-up — 23:39 CST

User explicitly requested further diagnosis while contacting the lab. At
23:34:49 CST one minimal request through the actual production urllib client
succeeded with the existing key, unchanged route, exact Gemini 3.8 Flash model,
valid JSON, and no retries; no benchmark judgment was rerun. The earlier
import-path failure occurred before any request. This proves current successful
authentication/generation, not durable resolution of the intermittent error.

The prior red-team completion receipt covers 240 assignments and all seven
stages (9,327 total judgments). Its historical log also records eight Gemini
location failures in the first full-trajectory pass, seven in post-update,
and 20 affected rubric jobs; recovery eventually completed them. Consequently
the same error predates the current comparator audit.

Read-only Clash inspection finds rule mode, active TUN/fake-IP DNS, and all
three API domains assigned to the same AI-services group. The live group selects
a Japan-labelled node through the general foreign-traffic selector. No active
API connection was present to inspect, and the available sidecar log contains
no Gemini hostname entries; this does not establish historical per-request
egress or Google's IP classification. No local routing defect is proven and
no networking setting was changed. See `routing-inspection.json` and
`current-access-diagnostic.json` in the Gemini provenance directory.

The [key-transition documentation](https://ai.google.dev/gemini-api/docs/api-key)
is a separate administrative check, **not an evidenced cause of this error**.
A [Google forum response](https://discuss.ai.google.dev/t/gemini-api-suddenly-returns-user-location-is-not-supported-after-enabling-billing-and-ai-studio-cannot-list-projects/172717/6)
points similar supported-region failures to Google's
[IP classification reporting form](https://support.google.com/websearch/workflow/9308722).
Do not infer that another provider's success proves Google's own classification
is correct, or that the VPN is definitely at fault. Full experiments remain
paused pending a supported resolution; latest user authorization supersedes
the older blanket prohibition on further diagnostic requests below.

## Latest 23:25 CST — region rejection reproduced

At 23:19:38.888 CST the current lab key again received HTTP 400
`FAILED_PRECONDITION: User location is not supported for the API use.` The
external supervisor stopped the audit within a second; 59 successful direct
judgments are preserved. No further requests are authorized by this workflow
until the lab/provider confirms legitimate access restoration. The earlier
successful metadata and generation checks did not establish durable eligibility.
See the [unsent support note](gemini-lab-access-support-note.md). Earlier running
checkpoints below are historical.

## Historical update — 23:05 CST

The user confirmed that `.env.local` contains the intended lab-provided key;
its absence from the personal AI Studio account is expected. The credential is
present without whitespace, competing GOOGLE_API_KEY, proxy or Vertex overrides.
At 23:00:48 CST, a single authenticated model metadata request returned HTTP 200
for `models/gemini-3.8-flash`. At 23:01:16 CST, one minimal SDK generation returned
valid JSON and the requested effective model, with no application retry.
The key and routing remain unchanged; access currently works, but this does not
identify the cause of the earlier intermittent location rejection.

The authorized Gemini-only formal audit is session 23809 at c4; diagnostic
receipts and launch provenance are in
`runs/biomnibench-results20-2026-09-06/provenance/gemini/`.
Do not switch to the personal key or resume Anthropic. Earlier next-step and
paused-status descriptions below are historical.

## Current observed rate limit

At 23:15:15 CST Google returned HTTP 429 `RESOURCE_EXHAUSTED` for
`GenerateContentPaidTierInputTokensPerModelPerMinute-PaidTier2`, quota 3,000,000
input tokens/minute for Gemini 3.8 Flash, with a roughly 44-second retry delay.
This is a rate-limit signal, not invalid credentials or proof that billing is
unavailable. The project belongs to the lab, so other lab usage may share the
limit; its contribution is unknown. An external process-group cooldown observer
(session 1779) now respects reported retry delays without changing prompts,
scoring source, credentials, or configured attempt counts.

## Current observed transport failure

At 23:11:55 CST the c2 resume observer captured urllib
`SSL: UNEXPECTED_EOF_WHILE_READING`; other full-trajectory jobs continue to
succeed. The exact failing operation is retained in
`logs/gemini-provider-errors.jsonl` under the current run. This establishes a
current TLS transport failure, not an invalid key or a renewed region rejection.
The initial c4 batch did not persist per-call errors, so its failures cannot all
be assigned this cause retrospectively. All saved judgments remain preserved.

## Observed evidence

- Scoped three-model acceptance produced successful Gemini direct judgments and
  23 saved Gemini rubric judgments, but two rubric-score attempts returned
  `400 FAILED_PRECONDITION: User location is not supported for the API use.`
- Rejected attempts are retained under the interrupted acceptance audit's
  `rubric_score/artifacts/0e8293f11bdb1f020f2c5e48326f1e3a/` and
  `rubric_score/artifacts/9694a888a7a056d387abed53884f1db4/` directories.
- The user reports a Japan IP. A read-only HTTPX request to ipinfo.io on the
  laptop returned JP / Tokyo / Tokyo at approximately 15:04 CST. The IP address
  was not printed or saved. This is a third-party observation for that request,
  not proof of Google's classification or the earlier failing request's egress.
- A parallel urllib query did not succeed. An initial Python default-CA query
  failed certificate verification; a follow-up used the same certifi trust roots
  as production, without disabling verification, and returned URLError. This
  diagnostic failure does not prove a Gemini certificate problem.
- Effective urllib and HTTPX proxy inspection exposed no active proxy mappings;
  HTTP(S)/ALL_PROXY and Vertex/base-URL overrides were absent in the inspected
  inherited/dotenv environment. This does not rule out OS-level network routing.
- Direct auditing uses urllib and the Google generativelanguage endpoint;
  whole-rubric scoring uses google-genai/HTTPX with GEMINI_API_KEY. The judge
  subprocess inherits the environment and removes GOOGLE_API_KEY for Gemini,
  preventing that alternate key from overriding the canonical credential.

## Official guidance and interpretation

[Google's supported regions](https://ai.google.dev/gemini-api/docs/available-regions)
include Japan. Google's page also distinguishes regional availability from
account age/verification requirements for AI Studio. A Japan-labelled IP alone
does not establish every access prerequisite or Google's own IP classification.

[Google's troubleshooting guidance](https://ai.google.dev/gemini-api/docs/troubleshooting)
recommends retrying transient errors such as 429/5xx, not 400/403 client errors;
its developer forum is the documented bug-report channel. Consequently, the
region rejection is not being retried as an ordinary transport failure.

The root cause is **not established**. Mixed successful/rejected requests could
reflect request-path or provider-side eligibility classification differences;
there is insufficient evidence to attribute the failure to concurrency, bad
keys, or rubric content. No alternate region, proxy, account or model was used
to evade a restriction. No Gemini API diagnostic calls were sent after the stop.

## Next permitted steps

1. Continue the user-approved OpenAI/Anthropic audit in its isolated directory;
   preserve all prior Gemini scores and label Gemini pending.
2. Check the affected project's AI Studio access/billing and account eligibility
   through the user's authorized account; do not change billing or purchase
   credits merely as a diagnostic experiment.
3. If access should be eligible, prepare a support report with UTC timestamps,
   error code/message, model, SDK version and the JP egress observation. Share
   project/request identifiers only through an authorized private support channel;
   never include API keys or benchmark payloads in public reports.
4. Resume a small Gemini check only after evidence establishes eligible access
   or the provider resolves the classification issue. Do not silently substitute
   another provider endpoint; that would require protocol and access review.
