# Existing canonical control: gap/RH ranking

Provider-free reuse of the existing ranking implementation on the nine completed
C00 control artifacts. No challenger artifact exists because all challengers
were blocked in the fixed feedback checks. This is descriptive development data.

Signed W−S, S−H and H−A are ranked worst/highest first with average ties. The raw
combined rank is their equal-weight mean; combined severity score is its
negative, so larger score means worse gaps. Both are retained in the [CSV](artifact-gap-rh-ranking.csv).
RH uses equal-weight Sol+Opus continuous scores. No abstentions occur here.
Constant-score correlations remain undefined in the unchanged implementation.

| Gap metric / severity score | Final-artifact Spearman | Kendall tau-b | Worst 10% / 20% / 25% overlap | Full-trajectory Spearman | Kendall tau-b | Worst 10% / 20% / 25% overlap |
|---|---:|---:|---|---:|---:|---|
| W−S | 0.661 | 0.578 | 1.000 / 0.500 / 0.750 | 0.768 | 0.657 | 1.000 / 0.500 / 1.000 |
| S−H | −0.496 | −0.369 | 0.000 / 0.000 / 0.167 | −0.534 | −0.420 | 0.000 / 0.000 / 0.333 |
| H−A | 0.346 | 0.289 | 1.000 / 0.500 / 0.500 | 0.428 | 0.340 | 1.000 / 0.500 / 0.667 |
| Combined severity score | 0.165 | 0.132 | 0.000 / 0.500 / 0.500 | 0.035 | −0.064 | 0.000 / 0.500 / 0.667 |

Raw mean combined-rank correlations have the opposite signs: final-artifact
Spearman −0.165/tau −0.132, trajectory Spearman −0.035/tau 0.064. Overlap uses
fractional membership at tied boundaries; n=9 means the three cutoffs select
1, 2 and 3 artifacts. The [JSON](artifact-gap-rh-ranking-summary.json) preserves
all tie membership and individual artifact values.

All final-artifact verdicts are negative, with mean combined rank 5.00; the
positive-group mean is undefined. Full trajectory has three panel-union-positive
artifacts (mean combined rank 3.89) and six negative (5.56). Lower rank is worse.
Monitor scores still vary when binary verdicts are all negative.

The different gap components do not show a uniform relationship with RH. The
near-zero combined/trajectory correlation is informative but cannot establish
independence with three task clusters. No feedback prompt was tuned from these
correlations and no challenger effect is inferred.
