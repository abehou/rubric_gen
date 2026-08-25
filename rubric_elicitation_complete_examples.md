# Complete offline and online rubric-elicitation examples

## Scope and transcription rules

This appendix gives two complete semantic elicitation examples from the
BioMNIBench `results20` study:

1. one offline rubric generation; and
2. one online rubric generation.

Both examples use task `da-12-2`, replicate 1, and full feedback. This keeps the
task and original rubric fixed.

Each example includes the complete contents of these semantic records:

1. blinded artifact history and pair graph;
2. difference-finder output;
3. criterion-proposer output;
4. semantic-reviewer output; and
5. final rendered rubric.

No semantic output is shortened. JSON indentation is added for readability.
All JSON keys, values, arrays, and ordering remain unchanged. The rendered
rubric text is copied without edits.

The machine provenance records contain request schemas, token usage, model
identifiers, hashes, and scoring-feasibility checks. They are not semantic model
outputs. The complete records remain available through the source links in each
example.

## Example 1: complete offline elicitation

### Source files

- [Generation provenance](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-offline-rubric/rubric-generations/bank-0001/generation.json)
- [Rubric-bank manifest](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-offline-rubric/rubric-banks/bank-0001/manifest.json)
- [Specification anchor](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-offline-rubric/rubric-banks/bank-0001/specification-anchor.txt)
- [Final rendered rubric](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-offline-rubric/rubric-banks/bank-0001/members/4b7b41fb5fb221028aa1d15ea595227d345b484b548f3e9e9f24713940f63bfb.txt)

This generation ran before the live trajectory. It used three sealed
pre-treatment artifacts and all three possible pairs.

### 1. Complete artifact history

Source:
[`artifact-history.json`](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-offline-rubric/rubric-generations/bank-0001/artifact-history.json)

```json
{
  "artifacts": [
    {
      "artifact_id": "artifact_34a50afd06bc3aaf",
      "content": "Yes. Using the union of unique genes listed in either experiment as the background (N=7,005), 1,543 genes were flagged as shared. HALLMARK_G2M_CHECKPOINT contains 121 background genes; 37 shared genes are in it versus 26.65 expected (1.39-fold enrichment). The one-sided hypergeometric enrichment p-value is 0.0171, below 0.05. This is conditional on the supplied DEG flags and does not establish causality or account for testing other pathways.\n",
      "content_sha256": "4e7f6a5439a59ad69f46d0b420590a8e727246515dd3ffc05b7f01b915d5cce2",
      "source_id": "sealed-seed:rep-003"
    },
    {
      "artifact_id": "artifact_388a5c7c71f48ae6",
      "content": "Yes. Using the union of all observed DEGs as the background (N=7,005), 37 of 1,543 shared overexpression/knockdown DEGs belonged to the Hallmark G2M_CHECKPOINT set (121 G2M genes were present in the background). A one-sided hypergeometric test gave p=0.0171, below 0.05, so G2M checkpoint is nominally enriched among the shared DEGs. This is an unadjusted over-representation result and does not establish causality.\n",
      "content_sha256": "fc9762ebeff862e601c29bb05875c6d410fe0100ddf57bb5e8e00dd2ce451b33",
      "source_id": "sealed-seed:rep-002"
    },
    {
      "artifact_id": "artifact_6a320149e69f9a72",
      "content": "Yes—at the requested nominal threshold. Among the 1,543 genes flagged as shared between the overexpression and knockdown DEG lists, 37 belong to the Hallmark G2M checkpoint set. Using the union of 7,556 unique DEG genes as the background (121 G2M genes) and a one-sided exact hypergeometric test, enrichment is p = 0.0171 (< 0.05).\n\nThis is not significant after Benjamini–Hochberg correction across the 50 Hallmark pathways (FDR = 0.2856), so the conclusion is nominal rather than multiplicity-adjusted.\n",
      "content_sha256": "f73f08dd22ead4afedccff51dd008ca61ad20d7aa27f81079e4988b968593323",
      "source_id": "sealed-seed:rep-001"
    }
  ],
  "kind": "blinded-artifact-history",
  "pairs": [
    {
      "artifact_ids": [
        "artifact_34a50afd06bc3aaf",
        "artifact_388a5c7c71f48ae6"
      ],
      "pair_id": "pair_78e221bfe9b1e651"
    },
    {
      "artifact_ids": [
        "artifact_34a50afd06bc3aaf",
        "artifact_6a320149e69f9a72"
      ],
      "pair_id": "pair_3818df617719ab3d"
    },
    {
      "artifact_ids": [
        "artifact_388a5c7c71f48ae6",
        "artifact_6a320149e69f9a72"
      ],
      "pair_id": "pair_6289f2db5722221f"
    }
  ]
}
```

### 2. Complete difference-finder output

Source:
[`difference-proposal.json`](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-offline-rubric/rubric-generations/bank-0001/difference-proposal.json)

```json
{
  "pairs": [
    {
      "pair_id": "pair_78e221bfe9b1e651",
      "differences": [
        {
          "summary": "The first artifact reports an expected overlap of 26.65 genes and a 1.39-fold enrichment; the second does not.",
          "task_relevance": "These quantify enrichment magnitude beyond the overlap and p-value."
        },
        {
          "summary": "The first explicitly conditions the result on supplied DEG flags and cautions that it does not account for testing other pathways; the second only calls it unadjusted and non-causal.",
          "task_relevance": "These are distinct scope and multiplicity caveats."
        }
      ]
    },
    {
      "pair_id": "pair_3818df617719ab3d",
      "differences": [
        {
          "summary": "The artifacts use different background sizes: 7,005 versus 7,556 unique genes.",
          "task_relevance": "The background definition changes the ORA population and interpretation."
        },
        {
          "summary": "The first reports expected overlap and 1.39-fold enrichment, whereas the second reports Benjamini–Hochberg FDR 0.2856 across 50 pathways.",
          "task_relevance": "These provide different quantitative context: effect magnitude versus an explicit multiplicity-adjusted result."
        }
      ]
    },
    {
      "pair_id": "pair_6289f2db5722221f",
      "differences": [
        {
          "summary": "The artifacts use different background sizes: 7,005 versus 7,556 unique genes.",
          "task_relevance": "The background definition changes the ORA population and interpretation."
        },
        {
          "summary": "The second reports FDR = 0.2856 across 50 Hallmark pathways and labels the finding nominal; the first reports only the raw p-value.",
          "task_relevance": "The exact correction scope and adjusted result materially qualify the nominal enrichment claim."
        }
      ]
    }
  ]
}
```

### 3. Complete criterion-proposer output

Source:
[`criterion-proposal.json`](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-offline-rubric/rubric-generations/bank-0001/criterion-proposal.json)

```json
{
  "criteria": [
    {
      "title": "Enrichment Magnitude and Scope Qualification",
      "requirement": "When claiming that the G2M pathway is enriched, the submission must report an interpretable enrichment magnitude (such as expected versus observed overlap or a fold-enrichment measure) and explicitly state the background/universe and the scope of multiplicity adjustment or other limitations affecting the claim.",
      "level_descriptions": [
        {
          "label": "A",
          "description": "Provides materialized quantitative enrichment magnitude, identifies the gene universe/background used, and clearly qualifies the inference with the testing scope and relevant limitations."
        },
        {
          "label": "B",
          "description": "Provides some quantitative magnitude or scope qualification, but omits an important component, such as the background definition, expected overlap, fold enrichment, or multiplicity scope."
        },
        {
          "label": "C",
          "description": "Claims or interprets enrichment without inspectable enrichment magnitude and without identifying the analysis universe or relevant scope limitations, or presents contradictory qualifications."
        }
      ],
      "support_pair_ids": [
        "pair_78e221bfe9b1e651",
        "pair_3818df617719ab3d",
        "pair_6289f2db5722221f"
      ]
    }
  ]
}
```

### 4. Complete semantic-reviewer output

Source:
[`criterion-edit.json`](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-offline-rubric/rubric-generations/bank-0001/criterion-edit.json)

```json
{
  "actions": [
    {
      "action": "rewrite",
      "source_criterion_ids": [
        "elicited_e0c637aca19a6cc6"
      ],
      "title": "Evidence-Consistent Enrichment Magnitude and Scope",
      "requirement": "When claiming that the G2M pathway is enriched, the submission must provide directly inspectable quantitative evidence for the enrichment magnitude (for example, observed versus expected overlap or a fold-enrichment measure), identify the gene universe/background used to compute it, and state the multiplicity-adjustment scope and other limitations that qualify the claim. The reported counts, calculations, background, and qualification must be mutually consistent and traceable to the analysis.",
      "level_descriptions": [
        {
          "label": "A",
          "description": "Provides reproducible quantitative evidence for enrichment magnitude, identifies the analysis universe/background, and clearly states the multiplicity scope and relevant limitations; these elements are mutually consistent and supported by inspectable calculations or output."
        },
        {
          "label": "B",
          "description": "Provides some inspectable magnitude or scope qualification but omits an important component, such as the background definition, expected overlap, fold enrichment, multiplicity scope, or consistency evidence."
        },
        {
          "label": "C",
          "description": "Claims or relies on enrichment without inspectable magnitude evidence and a defined analysis universe or scope qualification, or presents materially inconsistent counts, calculations, backgrounds, or caveats."
        }
      ],
      "support_pair_ids": [
        "pair_78e221bfe9b1e651",
        "pair_3818df617719ab3d",
        "pair_6289f2db5722221f"
      ],
      "reason": "Rewritten to make the penalty claim-conditional, require direct evidence and internal consistency, and avoid treating any observed artifact result as a required target. The requirement is supported across all three artifact pairs and targets an evidence/validity failure not fully captured by the existing rubric."
    }
  ]
}
```

### 5. Complete final offline rubric

```text
RUBRIC: DA-12-2

# Rubric for Q2: Over-Representation Analysis of Differentially Expressed Genes

Total Points: 100/100

Notes: This rubric assesses an over-representation analysis pipeline implementation. High-quality work correctly extracts and filters gene lists, applies suitable ORA using Fisher's exact test or the hypergeometric distribution, performs rigorous multiple-testing correction, reports accurate quantitative results for the G2M checkpoint pathway, and clearly presents enriched pathways.

CRITERIA (7):

Score normalization maximum: 100

Criterion 1: Accurate Gene List Extraction
Description: Evaluates whether the gene list is correctly loaded from and filtered using TS7.
Levels: A=20 B=10 C=0
[A]: Uses the TS7.xlsx file, obtains gene names from the appropriate gene-name column, retains genes whose designated column equals "v", removes NA and blank entries, eliminates duplicates, and produces approximately 1543 unique genes.
[B]: Uses TS7 with minor column-selection or filtering errors (for example, a slightly different count from alternative NA handling), but generates a largely overlapping gene set suitable for ORA.
[C]: Uses an incorrect file or sheet, disregards the required "v" filter, or generates a gene list of an incorrect size indicating a fundamental extraction error.

Criterion 2: Correct Gene Sets in ORA Implementation
Description: Assesses whether over-representation analysis is properly implemented with MSigDB Hallmark gene sets.
Levels: A=20 B=10 C=0
[A]: Performs over-representation analysis with Fisher's exact test or a hypergeometric distribution (through GSEApy, scipy.stats, or an equivalent library), uses the GSEA_gmt.gmt file containing MSigDB Hallmark gene sets as the pathway database, evaluates all Hallmark pathways (49 pathways total), and correctly configures the test with the extracted gene list as the query and Hallmark pathways as the background.
[B]: Performs ORA but uses an incorrect gene set collection (not Hallmark or not sourced from GSEA_gmt.gmt), provides unclear GMT file usage, or evaluates an incomplete pathway set.
[C]: Fails to perform ORA, applies an entirely inappropriate method (e.g., GSEA ranked analysis rather than ORA), or does not use suitable gene sets.

Criterion 3: Multiple-Comparison Adjustment and Significance Cutoff
Description: Evaluates whether multiple-testing adjustment is applied and significance is determined appropriately.
Levels: A=15 B=8 C=0
[A]: Provides both unadjusted p-values and FDR-adjusted p-values using Benjamini-Hochberg or an equivalent multiple-testing method, applies the specified p < 0.05 significance cutoff to FDR values when identifying significant pathways, and uses this cutoff consistently for every pathway assessment.
[B]: Provides only raw p-values or only FDR values rather than both, applies the significance cutoff properly but reports incompletely, or uses p < 0.05 without making clear whether it was applied to raw p-values or FDR values.
[C]: Omits multiple-testing adjustment, applies an incorrect significance cutoff, or identifies significance incorrectly.

Criterion 4: G2M Checkpoint Quantitative Results
Description: Assesses whether the quantitative results for the G2M checkpoint pathway accurately match the expected values.
Levels: A=25 B=12 C=0
[A]: Reports G2M checkpoint overlap of 37/200 genes (37 query genes among 200 total pathway genes), raw p-value approximately 1.69e-05, FDR approximately 2.76e-04, rank 3 of 49 pathways tested, and correctly concludes "YES" that the G2M checkpoint pathway is significantly enriched (FDR < 0.05).
[B]: Gives the correct "YES" conclusion and correct overlap count (37/200), but the p-value, FDR, or rank differs materially from the expected result (for example, because of a different background gene set or tool defaults), or omits one key quantitative value from the report.
[C]: Provides an incorrect conclusion (saying it is not significant when it should be significant), gives an incompatible overlap count, or reports fundamentally incorrect quantitative values.

Criterion 5: Overall ORA Results and Leading Pathways
Description: Evaluates whether the ORA findings report both the total pathways assessed and a ranked set of the most enriched pathways.
Levels: A=10 B=5 C=0
[A]: Reports testing of 49 Hallmark pathways, lists the leading enriched pathways in FDR order (at least the top 3-10), and gives pathway names plus key statistics, including overlap counts and FDR values, for those pathways; also notes significantly enriched pathways beyond the G2M checkpoint, such as MITOTIC_SPINDLE and UV_RESPONSE_DN.
[B]: Identifies leading enriched pathways but leaves out the total tested, fails to make FDR-based ranking clear, or gives incomplete top-pathway statistics.
[C]: Provides no overall ORA context, omits the leading pathways, or reports results so incompletely that the broader enrichment landscape cannot be understood.

Criterion 6: Clarity and Reproducibility
Description: Evaluates how clearly the methods are explained and whether the analysis can be reproduced.
Levels: A=10 B=5 C=0
[A]: Explicitly identifies the TS7.xlsx file and the particular columns used (the gene name column and the filter column marked with "v"), identifies GSEA_gmt.gmt as the Hallmark gene-set source, explains the ORA approach coherently (Fisher's exact test or hypergeometric, along with the multiple-testing correction method), reports results consistently, and includes enough information for reproduction.
[B]: Generally understandable but omits important references (such as the specific files or columns), has minor inconsistencies that do not materially change interpretation, or provides incomplete methodological detail.
[C]: The analysis cannot be reproduced because essential information about files, columns, or methods is absent, contradictions are present, or the account is too vague to determine what was done.

Criterion 7: Reliability of Sources
Description: Assesses whether the agent anchors its values, identifiers, and biological / clinical interpretations to identifiable sources, the supplied data files, named public databases, or genuine peer-reviewed references, instead of stating remembered facts without attribution.
Levels: A=0 B=-5 C=-10
[A]: Numerical results can be traced to the supplied data files or a documented transformation. Identifiers (gene / protein / sample / pathway names) originate from named sources (HGNC, UniProt, MSigDB, KEGG, the dataset's own feature index). Statistical method names accurately reflect what was run. Biological / clinical interpretations are backed by genuine, identifiable references (author + year + DOI / PubMed), not unsupported assertions.
[B]: Most numerical results and identifiers are traceable, though some interpretive claims lack source attribution or rely only on vague wording such as "studies show".
[C]: Values, identifiers, or biological claims are reported without a clear source. Hallucinated material (made-up identifiers, fabricated statistics, invented citations) is mixed with computed results.

Criterion 8: Evidence-Consistent Enrichment Magnitude and Scope
Apply this penalty only when the submission claims or relies on this property. Do not penalize an unclaimed optional feature. When claiming that the G2M pathway is enriched, the submission must provide directly inspectable quantitative evidence for the enrichment magnitude (for example, observed versus expected overlap or a fold-enrichment measure), identify the gene universe/background used to compute it, and state the multiplicity-adjustment scope and other limitations that qualify the claim. The reported counts, calculations, background, and qualification must be mutually consistent and traceable to the analysis.
Elicited criterion ID: elicited_5be62bd662bc5341
Levels: A=0 B=-2 C=-4
[A]: No covered claim is made, or the check passes: Provides reproducible quantitative evidence for enrichment magnitude, identifies the analysis universe/background, and clearly states the multiplicity scope and relevant limitations; these elements are mutually consistent and supported by inspectable calculations or output.
[B]: The submission claims or relies on the property, but the check fails: Provides some inspectable magnitude or scope qualification but omits an important component, such as the background definition, expected overlap, fold enrichment, multiplicity scope, or consistency evidence.
[C]: The submission claims or relies on the property, but the check fails: Claims or relies on enrichment without inspectable magnitude evidence and a defined analysis universe or scope qualification, or presents materially inconsistent counts, calculations, backgrounds, or caveats.
```

## Example 2: complete online elicitation

### Source files

- [Generation provenance](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-online-rubric/rubric-generations/bank-0003/generation.json)
- [Rubric-bank manifest](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-online-rubric/rubric-banks/bank-0003/manifest.json)
- [Specification anchor](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-online-rubric/rubric-banks/bank-0003/specification-anchor.txt)
- [Final rendered rubric](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-online-rubric/rubric-banks/bank-0003/members/4bab977dcca4da44d9c8e64edccf389747bfb1cd08947a620a51eb40445e054b.txt)

This is online update 3, sealed after `s003` and used to score `s004`.
Updates 1 and 2 proposed no criterion. `s001`, `s002`, and `s003` had identical
rendered content. Content deduplication kept one live artifact, `live:s001`.

### 1. Complete artifact history

Source:
[`artifact-history.json`](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-online-rubric/rubric-generations/bank-0003/artifact-history.json)

```json
{
  "artifacts": [
    {
      "artifact_id": "artifact_60785cd9a80be2fa",
      "content": "Yes. Using the union of all observed DEGs as the background (N=7,005), 37 of 1,543 shared overexpression/knockdown DEGs belonged to the Hallmark G2M_CHECKPOINT set (121 G2M genes were present in the background). A one-sided hypergeometric test gave p=0.0171, below 0.05, so G2M checkpoint is nominally enriched among the shared DEGs. This is an unadjusted over-representation result and does not establish causality.\n",
      "content_sha256": "fc9762ebeff862e601c29bb05875c6d410fe0100ddf57bb5e8e00dd2ce451b33",
      "source_id": "sealed-seed:rep-002"
    },
    {
      "artifact_id": "artifact_76b021995e0044dc",
      "content": "Yes—at the requested nominal threshold. Among the 1,543 genes flagged as shared between the overexpression and knockdown DEG lists, 37 belong to the Hallmark G2M checkpoint set. Using the union of 7,556 unique DEG genes as the background (121 G2M genes) and a one-sided exact hypergeometric test, enrichment is p = 0.0171 (< 0.05).\n\nThis is not significant after Benjamini–Hochberg correction across the 50 Hallmark pathways (FDR = 0.2856), so the conclusion is nominal rather than multiplicity-adjusted.\n",
      "content_sha256": "f73f08dd22ead4afedccff51dd008ca61ad20d7aa27f81079e4988b968593323",
      "source_id": "sealed-seed:rep-001"
    },
    {
      "artifact_id": "artifact_9771965025b6280e",
      "content": "Yes. The shared DEG set contains 1,543 unique genes (the intersection of the literal-v flag sets from the overexpression and knockdown columns). G2M checkpoint contains 37 of these 1,543 genes, out of 200 genes in the supplied Hallmark GMT set. Using a one-sided exact hypergeometric ORA with the specified 17,210-gene analysis background gives p = 1.69e-05; after Benjamini–Hochberg correction over 49 testable Hallmark pathways, FDR = 2.76e-04 (rank 3/49). Therefore G2M checkpoint is significantly enriched (FDR < 0.05, and nominal p < 0.05).\n\nThe leading pathways in FDR order are MITOTIC_SPINDLE (60 overlap; FDR 5.02e-16), UV_RESPONSE_DN (33; 9.10e-06), G2M_CHECKPOINT (37; 2.76e-04), PROTEIN_SECRETION (17; 5.96e-02), and TGF_BETA_SIGNALING (11; 7.41e-02). Only the first three of these pass FDR < 0.05. Results are an association from the supplied DEG table and gene sets; they do not establish mechanism, direction of pathway activity, or clinical causality.\n",
      "content_sha256": "fcff1c4cbc2a01af0627b862f9adb852c1dffbcd8e999875f4f1838c2f0f384f",
      "source_id": "live:s001"
    },
    {
      "artifact_id": "artifact_d0f1ef589be017c1",
      "content": "Yes. Using the union of unique genes listed in either experiment as the background (N=7,005), 1,543 genes were flagged as shared. HALLMARK_G2M_CHECKPOINT contains 121 background genes; 37 shared genes are in it versus 26.65 expected (1.39-fold enrichment). The one-sided hypergeometric enrichment p-value is 0.0171, below 0.05. This is conditional on the supplied DEG flags and does not establish causality or account for testing other pathways.\n",
      "content_sha256": "4e7f6a5439a59ad69f46d0b420590a8e727246515dd3ffc05b7f01b915d5cce2",
      "source_id": "sealed-seed:rep-003"
    }
  ],
  "kind": "blinded-artifact-history",
  "pairs": [
    {
      "artifact_ids": [
        "artifact_60785cd9a80be2fa",
        "artifact_76b021995e0044dc"
      ],
      "pair_id": "pair_c1082d9e98ec5df3"
    },
    {
      "artifact_ids": [
        "artifact_60785cd9a80be2fa",
        "artifact_9771965025b6280e"
      ],
      "pair_id": "pair_558066217c802fae"
    },
    {
      "artifact_ids": [
        "artifact_60785cd9a80be2fa",
        "artifact_d0f1ef589be017c1"
      ],
      "pair_id": "pair_63f77fa2b438124f"
    },
    {
      "artifact_ids": [
        "artifact_76b021995e0044dc",
        "artifact_9771965025b6280e"
      ],
      "pair_id": "pair_875c1731730e34e3"
    },
    {
      "artifact_ids": [
        "artifact_76b021995e0044dc",
        "artifact_d0f1ef589be017c1"
      ],
      "pair_id": "pair_9a60096b598341e8"
    },
    {
      "artifact_ids": [
        "artifact_9771965025b6280e",
        "artifact_d0f1ef589be017c1"
      ],
      "pair_id": "pair_bc5702c93850ab06"
    }
  ]
}
```

### 2. Complete difference-finder output

Source:
[`difference-proposal.json`](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-online-rubric/rubric-generations/bank-0003/difference-proposal.json)

```json
{
  "pairs": [
    {
      "pair_id": "pair_c1082d9e98ec5df3",
      "differences": [
        {
          "summary": "They use different background sizes: 7,005 versus 7,556 unique genes, despite reporting the same raw p-value.",
          "task_relevance": "The background definition materially affects reproducibility and interpretation of the enrichment calculation."
        },
        {
          "summary": "The second artifact additionally reports Benjamini–Hochberg FDR = 0.2856 across 50 Hallmark pathways and therefore distinguishes nominal from multiplicity-adjusted significance.",
          "task_relevance": "This clarifies the robustness of the enrichment conclusion beyond the nominal test."
        }
      ]
    },
    {
      "pair_id": "pair_558066217c802fae",
      "differences": [
        {
          "summary": "The artifacts use substantially different ORA universes and pathway sizes: 7,005-background/121 G2M genes versus a 17,210-gene background/200 G2M genes.",
          "task_relevance": "These choices produce materially different p-values and adjusted significance conclusions."
        },
        {
          "summary": "The second artifact reports pathway-level ranking and additional enriched pathways, whereas the first reports only G2M enrichment.",
          "task_relevance": "The broader pathway context helps interpret whether G2M is an isolated or shared enrichment signal."
        }
      ]
    },
    {
      "pair_id": "pair_63f77fa2b438124f",
      "differences": [
        {
          "summary": "Both report the same background, overlap, and p-value, but the second additionally reports 26.65 expected genes and 1.39-fold enrichment.",
          "task_relevance": "The expected count and effect-size description quantify the magnitude of over-representation rather than only its significance."
        }
      ]
    },
    {
      "pair_id": "pair_875c1731730e34e3",
      "differences": [
        {
          "summary": "They use different analysis backgrounds and G2M pathway sizes: 7,556/121 versus 17,210/200.",
          "task_relevance": "This methodological discrepancy explains the incompatible raw and adjusted significance results."
        },
        {
          "summary": "One concludes nominal enrichment but not FDR significance; the other concludes significance after FDR correction and supplies a ranked list of leading pathways.",
          "task_relevance": "The difference changes the substantive answer to whether enrichment is statistically supported after accounting for multiple testing."
        }
      ]
    },
    {
      "pair_id": "pair_9a60096b598341e8",
      "differences": [
        {
          "summary": "The first reports Benjamini–Hochberg FDR = 0.2856 across 50 pathways; the second reports only nominal p = 0.0171 and omits multiplicity adjustment.",
          "task_relevance": "The presence or absence of adjustment changes whether the result is presented as nominal rather than multiple-testing-supported."
        },
        {
          "summary": "The second reports 26.65 expected genes and 1.39-fold enrichment, which are absent from the first.",
          "task_relevance": "These values provide an interpretable enrichment magnitude."
        }
      ]
    },
    {
      "pair_id": "pair_bc5702c93850ab06",
      "differences": [
        {
          "summary": "They use different backgrounds and G2M pathway sizes: 17,210/200 versus 7,005/121, yielding p = 1.69e-05 versus 0.0171.",
          "task_relevance": "The choice of universe substantially changes the strength and interpretation of enrichment."
        },
        {
          "summary": "The first reports FDR = 2.76e-04 and a ranked multi-pathway result, while the second reports only nominal significance and an effect-size estimate of 1.39-fold.",
          "task_relevance": "The artifacts differ in both multiplicity-adjusted inference and quantitative characterization of enrichment."
        }
      ]
    }
  ]
}
```

### 3. Complete criterion-proposer output

Source:
[`criterion-proposal.json`](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-online-rubric/rubric-generations/bank-0003/criterion-proposal.json)

```json
{
  "criteria": [
    {
      "title": "Consistency of ORA Universe and Statistical Inference",
      "requirement": "When claiming G2M enrichment or significance, the submission must state the tested gene universe and pathway-set scope, identify the G2M pathway size and overlap basis, and ensure that reported p-values, FDR values, and conclusions are computed from those same denominators and multiplicity scope. Nominal and multiplicity-adjusted claims must not be conflated.",
      "level_descriptions": [
        {
          "label": "A",
          "description": "Provides a directly inspectable universe definition, pathway-set scope, overlap basis, and consistent quantitative record showing that the reported p-value, FDR, and significance conclusion correspond to those choices; clearly distinguishes nominal from adjusted inference."
        },
        {
          "label": "B",
          "description": "States most of the relevant universe or testing details and generally distinguishes nominal from adjusted inference, but omits a denominator, scope, or consistency check needed to fully verify the reported result."
        },
        {
          "label": "C",
          "description": "Claims enrichment or significance while using unstated, contradictory, or mismatched gene universes, pathway sizes, overlap bases, or multiplicity scopes, or lacks materialized evidence needed to verify the inference."
        }
      ],
      "support_pair_ids": [
        "pair_c1082d9e98ec5df3",
        "pair_558066217c802fae",
        "pair_9a60096b598341e8"
      ]
    }
  ]
}
```

### 4. Complete semantic-reviewer output

Source:
[`criterion-edit.json`](runs/studies/biomnibench-da-factorial-r6-5d56fee68932/experiments/da-12-2/rep-001/full-online-rubric/rubric-generations/bank-0003/criterion-edit.json)

```json
{
  "actions": [
    {
      "action": "rewrite",
      "source_criterion_ids": [
        "elicited_ad3c97ba96fd599d"
      ],
      "title": "Internal Consistency of Reported Enrichment Inference",
      "requirement": "When claiming G2M enrichment or statistical significance, the submission must provide directly inspectable evidence that the reported overlap, pathway size, gene universe, and multiplicity scope are the inputs for the reported p-value and FDR, and must distinguish nominal from multiplicity-adjusted conclusions. Apply this penalty only when the submission makes such an enrichment or significance claim.",
      "level_descriptions": [
        {
          "label": "A",
          "description": "Provides an inspectable calculation record linking the overlap, pathway size, gene universe, and multiplicity scope to the reported p-value and FDR, with conclusions clearly labeled as nominal or multiplicity-adjusted."
        },
        {
          "label": "B",
          "description": "Reports most relevant denominators and distinguishes nominal from adjusted inference, but leaves one material input or linkage insufficiently inspectable."
        },
        {
          "label": "C",
          "description": "Makes an enrichment or significance claim using unstated, contradictory, or mismatched inputs, conflates nominal and adjusted inference, or provides no inspectable evidence supporting the claimed calculation."
        }
      ],
      "support_pair_ids": [
        "pair_c1082d9e98ec5df3",
        "pair_558066217c802fae",
        "pair_9a60096b598341e8"
      ],
      "reason": "Rewritten to narrow the criterion to a claim-conditional, penalty-only check of internal statistical consistency and inspectable evidence. It avoids prescribing an observed result while addressing materially conflicting universes, pathway sizes, and multiplicity conclusions supported across three artifact pairs."
    }
  ]
}
```

### 5. Complete final online rubric

```text
RUBRIC: DA-12-2

# Rubric for Q2: Over-Representation Analysis of Differentially Expressed Genes

Total Points: 100/100

Notes: This rubric assesses an over-representation analysis pipeline implementation. High-quality work correctly extracts and filters gene lists, applies suitable ORA using Fisher's exact test or the hypergeometric distribution, performs rigorous multiple-testing correction, reports accurate quantitative results for the G2M checkpoint pathway, and clearly presents enriched pathways.

CRITERIA (7):

Score normalization maximum: 100

Criterion 1: Accurate Gene List Extraction
Description: Evaluates whether the gene list is correctly loaded from and filtered using TS7.
Levels: A=20 B=10 C=0
[A]: Uses the TS7.xlsx file, obtains gene names from the appropriate gene-name column, retains genes whose designated column equals "v", removes NA and blank entries, eliminates duplicates, and produces approximately 1543 unique genes.
[B]: Uses TS7 with minor column-selection or filtering errors (for example, a slightly different count from alternative NA handling), but generates a largely overlapping gene set suitable for ORA.
[C]: Uses an incorrect file or sheet, disregards the required "v" filter, or generates a gene list of an incorrect size indicating a fundamental extraction error.

Criterion 2: Correct Gene Sets in ORA Implementation
Description: Assesses whether over-representation analysis is properly implemented with MSigDB Hallmark gene sets.
Levels: A=20 B=10 C=0
[A]: Performs over-representation analysis with Fisher's exact test or a hypergeometric distribution (through GSEApy, scipy.stats, or an equivalent library), uses the GSEA_gmt.gmt file containing MSigDB Hallmark gene sets as the pathway database, evaluates all Hallmark pathways (49 pathways total), and correctly configures the test with the extracted gene list as the query and Hallmark pathways as the background.
[B]: Performs ORA but uses an incorrect gene set collection (not Hallmark or not sourced from GSEA_gmt.gmt), provides unclear GMT file usage, or evaluates an incomplete pathway set.
[C]: Fails to perform ORA, applies an entirely inappropriate method (e.g., GSEA ranked analysis rather than ORA), or does not use suitable gene sets.

Criterion 3: Multiple-Comparison Adjustment and Significance Cutoff
Description: Evaluates whether multiple-testing adjustment is applied and significance is determined appropriately.
Levels: A=15 B=8 C=0
[A]: Provides both unadjusted p-values and FDR-adjusted p-values using Benjamini-Hochberg or an equivalent multiple-testing method, applies the specified p < 0.05 significance cutoff to FDR values when identifying significant pathways, and uses this cutoff consistently for every pathway assessment.
[B]: Provides only raw p-values or only FDR values rather than both, applies the significance cutoff properly but reports incompletely, or uses p < 0.05 without making clear whether it was applied to raw p-values or FDR values.
[C]: Omits multiple-testing adjustment, applies an incorrect significance cutoff, or identifies significance incorrectly.

Criterion 4: G2M Checkpoint Quantitative Results
Description: Assesses whether the quantitative results for the G2M checkpoint pathway accurately match the expected values.
Levels: A=25 B=12 C=0
[A]: Reports G2M checkpoint overlap of 37/200 genes (37 query genes among 200 total pathway genes), raw p-value approximately 1.69e-05, FDR approximately 2.76e-04, rank 3 of 49 pathways tested, and correctly concludes "YES" that the G2M checkpoint pathway is significantly enriched (FDR < 0.05).
[B]: Gives the correct "YES" conclusion and correct overlap count (37/200), but the p-value, FDR, or rank differs materially from the expected result (for example, because of a different background gene set or tool defaults), or omits one key quantitative value from the report.
[C]: Provides an incorrect conclusion (saying it is not significant when it should be significant), gives an incompatible overlap count, or reports fundamentally incorrect quantitative values.

Criterion 5: Overall ORA Results and Leading Pathways
Description: Evaluates whether the ORA findings report both the total pathways assessed and a ranked set of the most enriched pathways.
Levels: A=10 B=5 C=0
[A]: Reports testing of 49 Hallmark pathways, lists the leading enriched pathways in FDR order (at least the top 3-10), and gives pathway names plus key statistics, including overlap counts and FDR values, for those pathways; also notes significantly enriched pathways beyond the G2M checkpoint, such as MITOTIC_SPINDLE and UV_RESPONSE_DN.
[B]: Identifies leading enriched pathways but leaves out the total tested, fails to make FDR-based ranking clear, or gives incomplete top-pathway statistics.
[C]: Provides no overall ORA context, omits the leading pathways, or reports results so incompletely that the broader enrichment landscape cannot be understood.

Criterion 6: Clarity and Reproducibility
Description: Evaluates how clearly the methods are explained and whether the analysis can be reproduced.
Levels: A=10 B=5 C=0
[A]: Explicitly identifies the TS7.xlsx file and the particular columns used (the gene name column and the filter column marked with "v"), identifies GSEA_gmt.gmt as the Hallmark gene-set source, explains the ORA approach coherently (Fisher's exact test or hypergeometric, along with the multiple-testing correction method), reports results consistently, and includes enough information for reproduction.
[B]: Generally understandable but omits important references (such as the specific files or columns), has minor inconsistencies that do not materially change interpretation, or provides incomplete methodological detail.
[C]: The analysis cannot be reproduced because essential information about files, columns, or methods is absent, contradictions are present, or the account is too vague to determine what was done.

Criterion 7: Reliability of Sources
Description: Assesses whether the agent anchors its values, identifiers, and biological / clinical interpretations to identifiable sources, the supplied data files, named public databases, or genuine peer-reviewed references, instead of stating remembered facts without attribution.
Levels: A=0 B=-5 C=-10
[A]: Numerical results can be traced to the supplied data files or a documented transformation. Identifiers (gene / protein / sample / pathway names) originate from named sources (HGNC, UniProt, MSigDB, KEGG, the dataset's own feature index). Statistical method names accurately reflect what was run. Biological / clinical interpretations are backed by genuine, identifiable references (author + year + DOI / PubMed), not unsupported assertions.
[B]: Most numerical results and identifiers are traceable, though some interpretive claims lack source attribution or rely only on vague wording such as "studies show".
[C]: Values, identifiers, or biological claims are reported without a clear source. Hallucinated material (made-up identifiers, fabricated statistics, invented citations) is mixed with computed results.

Criterion 8: Internal Consistency of Reported Enrichment Inference
Apply this penalty only when the submission claims or relies on this property. Do not penalize an unclaimed optional feature. When claiming G2M enrichment or statistical significance, the submission must provide directly inspectable evidence that the reported overlap, pathway size, gene universe, and multiplicity scope are the inputs for the reported p-value and FDR, and must distinguish nominal from multiplicity-adjusted conclusions. Apply this penalty only when the submission makes such an enrichment or significance claim.
Elicited criterion ID: elicited_d1e954c63c14c5c6
Levels: A=0 B=-2 C=-4
[A]: No covered claim is made, or the check passes: Provides an inspectable calculation record linking the overlap, pathway size, gene universe, and multiplicity scope to the reported p-value and FDR, with conclusions clearly labeled as nominal or multiplicity-adjusted.
[B]: The submission claims or relies on the property, but the check fails: Reports most relevant denominators and distinguishes nominal from adjusted inference, but leaves one material input or linkage insufficiently inspectable.
[C]: The submission claims or relies on the property, but the check fails: Makes an enrichment or significance claim using unstated, contradictory, or mismatched inputs, conflates nominal and adjusted inference, or provides no inspectable evidence supporting the claimed calculation.
```

## Direct comparison

The offline and online outputs detect the same core problem through different
evidence.

The offline output sees disagreement among three sealed answers. It creates a
broad check for enrichment magnitude, background definition, multiplicity
scope, and internal consistency.

The online output also sees the live 17,210-gene answer. Its final criterion is
narrower. It requires the reported overlap, pathway size, gene universe,
multiplicity scope, p-value, and false-discovery-rate value to form one
inspectable calculation record.

The reviewer rewrites both proposals. This is important. The final rubrics are
not the proposer's raw output.
