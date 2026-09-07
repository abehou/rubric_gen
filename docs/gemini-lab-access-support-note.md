# Gemini access investigation for the lab

Prepared 2026-09-06. This note has not been sent to anyone. It contains no API key,
benchmark payload, account identifier, or private IP address.

The existing lab-provided key authenticates successfully, but generation access
intermittently fails with a location rejection. Please confirm that the project
permits use from the current execution location and ask Google to investigate
its eligibility classification. No key replacement, account switch, proxy,
region change, model substitution, or billing change has been made.

| Time (UTC, 2026-09-06) | Observed result |
| --- | --- |
| 15:00:48 | Authenticated model metadata lookup returned HTTP 200 for `models/gemini-3.8-flash`. |
| 15:01:16 | A minimal Google Gen AI SDK generation returned valid JSON with effective model `gemini-3.8-flash`. |
| 15:11:55 onward | Some urllib calls failed with TLS unexpected EOF or remote disconnect; other judgments succeeded. |
| 15:15:15 | HTTP 429 identified the paid-tier-2 input-token quota: 3,000,000 tokens per model per minute, with a roughly 44-second retry delay. |
| 15:19:38.888 | HTTP 400, `FAILED_PRECONDITION`: “User location is not supported for the API use.” |
| 15:19:39.034 | External supervisor stopped the audit; all successful judgments were preserved. |
| 15:34:49 | A user-authorized minimal production-client generation succeeded with the unchanged key and routing, without retries. |

The model is `gemini-3.8-flash`, using Google's standard
`generativelanguage.googleapis.com/v1beta` endpoint. Direct judgments use the
existing urllib client; rubric scoring uses Google Gen AI/HTTPX. No key-value,
proxy, Vertex, or alternative endpoint override was found in the experiment
environment. A previous third-party egress observation reported Japan; that
observation does not establish Google's own classification or the actual route
for the rejected request.

The local audit has 59 saved, validated full-trajectory judgments out of 240;
other formal Gemini stages remain unstarted. OpenAI is complete and unchanged.
Anthropic remains paused separately. The project belongs to the lab, so other
usage may share its per-minute quota; that contribution is unknown.

Google documents Japan among [available regions](https://ai.google.dev/gemini-api/docs/available-regions),
but availability alone does not establish this project's eligibility. Google's
[troubleshooting guidance](https://ai.google.dev/gemini-api/docs/troubleshooting)
distinguishes transient rate/transport failures from 400/403 errors that should
not be repeatedly retried without addressing their cause.

Needed before another Gemini request: lab/provider confirmation that access from
the intended execution location is eligible and the intermittent rejection has
been resolved. If the project remains restricted, provide the provider's guidance
for legitimate access; do not reroute requests to evade the restriction.

Local evidence:

- `runs/biomnibench-results20-2026-09-06/provenance/gemini/metadata-access.json`
- `runs/biomnibench-results20-2026-09-06/provenance/gemini/generation-access.json`
- `runs/biomnibench-results20-2026-09-06/logs/gemini-provider-errors.jsonl`
- `runs/biomnibench-results20-2026-09-06/logs/gemini-resume-supervisor.log`
- `runs/biomnibench-results20-2026-09-06/provenance/gemini/region-pause-verification.json`

Further clarification: the completed original red-team run also encountered this exact location error before successful recovery. No evidence links it to the Standard/Auth key transition; key-type verification is only a separate administrative check. Read-only Clash inspection shows the three API domains configured to the same Japan-labelled selection, without proving Google’s geolocation of individual requests.

Controlled-resume result: at 15:45:44.913 UTC on September 6, the same location error returned at concurrency 1 after one new successful judgment. The supervisor stopped immediately; 60 judgments are now preserved. This shows lowering concurrency did not eliminate the rejection.
