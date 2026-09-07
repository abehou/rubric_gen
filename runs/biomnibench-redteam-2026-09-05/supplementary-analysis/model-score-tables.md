# RH scores by audit model

Final-checkpoint means, computed separately for each audit model. Direct RH detection rate = detected cases / total cases; Mean RH score = average final-artifact judge score (0–10).

The first three columns are score-point differences. Holdout scores are averaged across variants within each case before taking the condition mean. Every case has equal weight.

## gpt-5.6-sol

| Condition | weak − strong | selected − holdout | original − rubric-free | Direct final-artifact RH | Mean RH score |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full + red-team artifact | 5.97 | 0.22 | 22.90 | 5.0% | 0.63 |
| Full + red-team trace | 9.50 | -0.46 | 22.27 | 3.3% | 0.63 |
| User simulator + red-team artifact | 7.92 | 1.74 | 6.15 | 0.0% | 0.15 |
| User simulator + red-team trace | 9.98 | -0.99 | 5.53 | 0.0% | 0.22 |

## claude-opus-5

| Condition | weak − strong | selected − holdout | original − rubric-free | Direct final-artifact RH | Mean RH score |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full + red-team artifact | 4.15 | 1.06 | 18.48 | 3.3% | 1.30 |
| Full + red-team trace | 5.20 | -0.71 | 18.92 | 0.0% | 1.25 |
| User simulator + red-team artifact | 4.03 | -1.34 | 10.52 | 0.0% | 1.00 |
| User simulator + red-team trace | 4.27 | -0.70 | 12.57 | 0.0% | 0.93 |

## gemini-3.8-flash

| Condition | weak − strong | selected − holdout | original − rubric-free | Direct final-artifact RH | Mean RH score |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full + red-team artifact | 0.90 | 0.05 | -0.65 | 0.0% | 0.08 |
| Full + red-team trace | 0.52 | -0.34 | 2.37 | 0.0% | 0.07 |
| User simulator + red-team artifact | -0.97 | -0.28 | -4.20 | 0.0% | 0.00 |
| User simulator + red-team trace | -1.30 | -0.20 | -2.90 | 0.0% | 0.00 |
