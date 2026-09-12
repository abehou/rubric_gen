"""Provider-free, manually adjudicated diagnostic review; preserves model outputs."""
from collections import Counter
import csv,json,os
from pathlib import Path
B=Path(__file__).resolve().parent; ROOT=B.parents[1]
R=ROOT/'docs/reports/2026-09-12/trace-user-public-evidence-firewall'
# Labels describe this saved response, not a new outcome auditor or hidden test.
# (finding, useful content, source spans). Definite blocking examples are marked
# separately below; ambiguous/mixed recommendations are not counted as proven errors.
NOTES={
('P1','private_target_counts'):(
 'No private protein examples or expected concordance conclusion. Issue 1 nevertheless says missingness and retained dimensions are not computed/displayed, despite shape/isna prints and the reported output. Issue 3 treats canonical file sections as insufficient creation evidence; this is an unnecessary workspace-verification demand, not proof files were absent.',
 'Requests checkable intermediate accounting; multiplicity/exploratory framing is a plausible verification topic, though not proof the existing biological conclusion is wrong.',[(24,35),(98,111)]),
('P2','private_target_counts'):(
 'No private protein examples or expected conclusion. Verifier 2 overstates separate comparator analyses as pooling; renderer downgrades to a public comparability question rather than asserting a wrong numerical answer.',
 'Public references/documentation request and verification of cross-model comparability survive. No claim that zero named leakage proves general immunity.',[(37,64),(93,111)]),
('P1','different_populations'):(
 'Correctly drops the numerical contradiction candidate, but issue 3 incorrectly imports the exploratory composite requirement of an available adjusted p-value into the primary fixed-stratum rule, which explicitly needs only an available MHT estimate.',
 'No false 109-versus-212 arithmetic allegation survives; the remaining concern is a scope error.',[(97,120),(122,140)]),
('P2','different_populations'):(
 'All three candidates are rejected as unsupported. Verifier explicitly distinguishes primary all-GAHT-significant denominators, exploratory selection, and joint-FDR sensitivity.',
 'Correctly avoids forcing a repeated population/count correction on the current artifact.',[(97,120),(199,209),(219,227)]),
('P1','coefficient_coding_sign'):(
 'Does not repeat the sign-reversal allegation. Two separate renders duplicate the real scalar-WLS/count-model mismatch. The proteomics demand overstates a background dataset description as an explicit requirement; actual file availability is unresolved in this public packet.',
 'Identifies constant per-gene weights on log expression and unused off; a scalar WLS weight cancels, so this is not the claimed NB fit. A full package-only remedy is not established as the only valid implementation.',[(53,81),(92,116)]),
('P2','coefficient_coding_sign'):(
 'Verifier 1 and renderer 1 incorrectly say the prose calls the raw disease_Control coefficient ALS-minus-Control. The prose states the intended disease contrast; negating the Control dummy implements it. This is a false internal-inconsistency allegation, not literally the old claim that negation reverses the contrast. Historical changes in gene counts do not themselves establish a current contradiction.',
 'Other concerns retain the real scalar-WLS defect and request a public summary of negative effects; do not dismiss those because the sign concern is false.',[(53,81),(92,116)]),
('P1','unavailable_remedy'):(
 'Keeps a real missing sensitivity-script concern, twice. Reanalysis request is conditional on package feasibility and recognizes the conflict between public task installation permission and artifact-reported prohibition. The claim that diagnostic code is absent is overbroad: a quantile print is shown, while captured numeric outputs are missing.',
 'Local executable sensitivity code/captured outputs are useful even if the preferred package is unavailable.',[(41,67),(75,107),(121,150)]),
('P2','unavailable_remedy'):(
 'Three independent renders converge on substantially the same package/method concern, rather than retaining the specific missing sensitivity-code check. Conditionals avoid asserting availability, but repeated package-only demands and withdrawing the primary answer remain oversteering risks.',
 'The WLS validity concern is real; current outputs are openly qualified. Missing executable sensitivity code is a missed useful local check.',[(41,67),(75,107),(140,150)]),
('P1','repeated_count_concern'):(
 'Both candidates return no_issue. No new demand to change reconciled counts.',
 'Current 212=167+45 and distinct joint-FDR denominators are retained.',[(95,123),(208,236)]),
('P2','repeated_count_concern'):(
 'Three verifiers reject stale inconsistency/implementation/documentation concerns. They explicitly compute the sums and separate joint-FDR denominators.',
 'Correctly rejects the old fabricated 167-availability reading.',[(95,123),(208,236)]),
('P1','corrective_learned_check'):(
 'Retains a useful question about outcome-dependent smaller-p selection and asks for non-selection-based sensitivity. A generic rerun request lacks a specific numerical contradiction; lack of a raw log alone is not proof the reported outputs were not computed.',
 'Scientific caution about headline concordance after per-protein selection survives from public evidence without receiving the selected requirement as a new private channel.',[(97,121),(176,208)]),
('P2','corrective_learned_check'):(
 'Both candidates rejected; verifier treats implementation of the selected endpoint as sufficient and overlooks the methodological value of a non-selection-based primary comparison. This is a concern-retention weakness, with severity less definite than the executable defects in sensitivity_verification.',
 'The unchanged separate learned reminder would still be available in a trajectory; no solver exposure occurred in this diagnostic.',[(97,121),(176,208)]),
('P1','proactive_label_substantive_check'):(
 'Both candidates return no_issue. No host origin-tag rewrite was used.',
 'Current arithmetic and explicit reporting resolve the cited implementation/accounting concerns; absence of all possible issues is not established.',[(101,119),(143,158),(179,207)]),
('P2','proactive_label_substantive_check'):(
 'Three verifiers return unsupported after recognizing current code, assertions and reconciled tables.',
 'Accept is the public review outcome, not suppression based on a proactive label.',[(101,119),(143,158),(179,207)]),
('P1','proactive_only_request'):(
 'Claims there is no explicit cohort-definition step with intermediate counts, although Step 1 provides filters, prints and cohort counts. A generic rerun request is not evidence an execution failed. Additional identifier/missingness checks could be useful, but should not be framed as absence of the displayed cohort step.',
 'Asks to verify CNA lookups/union rather than supplying a hidden expected event count. This fixture is not a verified error-free accept oracle.',[(13,39),(47,71),(92,109)]),
('P2','proactive_only_request'):(
 'Both candidates rejected; current event definitions and public outputs recognized. The verifier accepts the disclosed metastatic/post-therapy operational assumption; this does not establish the assumption scientifically matches every task exposure.',
 'No proactive tag forces revise or host accept. Scope uncertainty remains, so accept is not labeled a proven globally correct verdict.',[(13,45),(92,122)]),
('P1','unmet_base_requirement'):(
 'Method validation is useful. Issue 3 requests recomputation/ordering verification despite the shared loc[sample_ids] ordering; a mismatch is not established, but the request to add an assertion is not counted as a definite false factual claim. First concern ends with a malformed partial word, exactly as generated.',
 'RNA-seq variance/sensitivity validation remains useful. Asking for an explicit ordering assertion is acceptable as a check, not evidence the displayed indexing is inconsistent.',[(29,45),(63,87),(105,111)]),
('P2','unmet_base_requirement'):(
 'Retains method verification and correctly notices CD68 is in the final answer but absent from the trace positive list. The proteomics concern is conditional on actual availability; the task background mentions that dataset but the listed local inputs do not include it.',
 'The CD68 reconciliation request is grounded in public text, not private named-answer guidance; it is a verification request, not proof CD68 is not differential.',[(9,16),(105,128)]),
('P1','cohort_scope_ambiguity'):(
 'Raises the real non-naive-versus-post-hormonal exposure ambiguity and broad mutation/CNA event rule. TUMOR_TISSUE_ORIGIN alone is not proven to encode actual therapy exposure, so a mandatory replacement column is stronger than the public evidence supports.',
 'Scope verification, functional-event justification and specific references are useful; no hidden gene-set answer is supplied.',[(17,39),(41,71),(117,132)]),
('P2','cohort_scope_ambiguity'):(
 'Twice retains the real missing sensitivity-union code and once the broad event-definition issue. One renderer offers labeling as independently verified as an alternative to code; that wording is insufficient without actual verification. Duplicate requests consume slots.',
 'Shown alternate-cohort code never computes the claimed 82 altered/11.63% result. Counts come from the public artifact, not a private target.',[(41,71),(99,121)]),
('P1','sensitivity_verification'):(
 'Two independent renders falsely say repeated fit_run writes leave only the final run or that aggregation is absent. Line 156 writes DataFrame(rows) after the loop. One render also catches the real dc/disease_col mismatch. Neither catches the rowwise sign comparison after independently sorting results.',
 'Variable-name repair survives but is bundled with a false overwrite allegation; output is preserved unchanged, including a truncated ending.',[(60,63),(103,106),(138,156),(171,175)]),
('P2','sensitivity_verification'):(
 'All three verifiers reject the candidates and the pipeline accepts. Verifier 2 claims variable names were reconciled, but setup defines disease_col and the function reads dc. Both result tables are independently sorted/reset before positional sign comparison. These two concrete executable defects are lost.',
 'Correctly avoids the false overwrite allegation, at the cost of suppressing useful local corrections. Lower concern count is not success.',[(60,63),(103,106),(138,156),(171,175)]),
('P1','partial_analysis_method'):(
 'Retains failed-fit accounting but mixes it with an unsupported normalization-order suspicion. Source code already uses normalized mu for dispersion. Does not flag the displayed doubled chi-square tail. Second concern ends in malformed generated text; no host truncation/repair applied.',
 'Public mismatch between reported failed fits and a loop lacking handling is real. Need for scientific validation is distinct from requiring a specific package.',[(43,76),(102,125)]),
('P2','partial_analysis_method'):(
 'Retains validation/failed-fit concerns. Verifier 3 and renderer 3 say dispersion-cap handling is not shown, although alpha=min(max(...),10) is explicit. Pre-filter size-factor estimation is not intrinsically invalid. Also misses the doubled chi-square tail.',
 'Failed-fit accounting survives; the code-level p-value defect is a missed opportunity in both candidates, not a claim that all other concerns are useless.',[(43,76),(102,125)]),
}
# Conservative definite failure accounting, at checkpoint level; findings may
# overlap. B is false public assertion, not evidence of hidden model cognition.
FLAGS={
 ('P1','private_target_counts'):['D'],
 ('P1','different_populations'):['C'],
 ('P1','proactive_only_request'):['D'],
 ('P1','sensitivity_verification'):['D'],
 ('P2','coefficient_coding_sign'):['B'],
 ('P2','sensitivity_verification'):['D','E'],
 ('P2','partial_analysis_method'):['D'],
}


def main():
    if not os.environ.get('SLURM_JOB_ID'): raise RuntimeError('raw data are compute-only; run this report script through Slurm')
    data=json.loads(Path('/data/user_data/aydanh/rubric_gen/runs/trace-user-public-evidence-firewall-20260912/feedback-checks/feedback-results.json').read_text())
    sources={r['case']:json.loads(Path(r['source']).read_text()) for r in data['rows']}
    rows=[];stage_rows=[];leaks=[]
    for row in data['rows']:
        cell,case=row['cell'],row['case'];src=sources[case];finding,useful,ranges=NOTES[cell,case]
        evidence=[];lines=src['current_artifact'].splitlines(keepends=True)
        for start,end in ranges:
            assert 1<=start<=end<=len(lines)
            evidence.append({'source':'artifact','start_line':start,'end_line':end,'text':''.join(lines[start-1:end])})
        rec={'cell':cell,'case':case,'task':src['task'],'replicate':src['replicate'],'submission_id':src['submission_id'],
             'result_path':row['result_path'],'original_feedback_path':src['feedback_generation_path'],
             'source_input_path':row['source'],'selected_legacy_reminder':src['selection'],
             'output':row['output'],'blocking_categories':FLAGS.get((cell,case),[]),
             'finding':finding,'useful_or_retained_content':useful,'public_evidence':evidence}
        rows.append(rec)
        for stage in row['stages']:
            stage_rows.append({'cell':cell,'case':case,'stage':stage['stage'],'output':stage['output'],
                               'saved_stage_path':stage['request_path'],
                               'attempts':[{'status':a['status'],'provider':a.get('provider'),
                                            'wall_seconds':a['wall_seconds']} for a in stage['attempts']]})
        if case=='private_target_counts':
            public={'task':src['instruction'],'artifact':src['current_artifact'],'history':src['history_context']}
            private=json.dumps(src['full_feedback'])
            for name in ('CXCL13','NOS3'):
                leaks.append({'cell':cell,'entity':name,'public_occurrences':{k:v.count(name) for k,v in public.items()},
                              'private_occurrences':private.count(name),'new_solver_feedback_occurrences':json.dumps(row['output']).count(name),
                              'selected_dynamic_check':src['selection'] is not None,
                              'result_path':row['result_path']})
    R.mkdir(exist_ok=True,parents=True)
    (R/'feedback-review.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False)+'\n')
    (R/'stage-responses.json').write_text(json.dumps(stage_rows,indent=2,ensure_ascii=False)+'\n')
    (R/'private-target-accounting.json').write_text(json.dumps(leaks,indent=2)+'\n')
    fields=['cell','case','task','replicate','submission_id','decision','concerns','blocking_categories','finding','useful_or_retained_content','result_path']
    with (R/'feedback-review.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in rows:writer.writerow({k:(r['output']['decision'] if k=='decision' else len(r['output']['concerns']) if k=='concerns' else '|'.join(r[k]) if k=='blocking_categories' else r[k]) for k in fields})
    text=['# Fixed feedback review','', 'All 24 responses reviewed against saved public artifacts. Model outputs remain unchanged. Categories B–E are conservative confirmed failure flags; additional ambiguities and mixed concerns are described rather than promoted to certain errors.','']
    for r in rows:
        text += [f"## {r['cell']} — {r['case']}",'',f"Saved {r['task']}/rep-{r['replicate']:03d}/{r['submission_id']}. Decision **{r['output']['decision']}**, {len(r['output']['concerns'])} concerns. Flags: {','.join(r['blocking_categories']) or 'none confirmed' }.",'',r['finding'],'',r['useful_or_retained_content'],'',f"Public source spans: {', '.join(str(e['start_line'])+'–'+str(e['end_line']) for e in r['public_evidence'])}. Exact excerpts and native paths are in [JSON](feedback-review.json).",'']
        for c in r['output']['concerns']:text += ['> '+c['feedback'],'']
    (R/'feedback-review.md').write_text('\n'.join(text)+'\n')
    counts={cell:dict(Counter(flag for r in rows if r['cell']==cell for flag in r['blocking_categories'])) for cell in ('P1','P2')}
    decision={'P1':{'decision':'blocked','primary':'repeated false public-code allegations, including diagnostics overwrite'},
              'P2':{'decision':'blocked','primary':'loss of two genuine executable corrections at sensitivity checkpoint, plus false public assertions'},
              'confirmed_checkpoint_flags':counts,'new_canonical_assignments':0,'new_outcome_judgments':0,
              'note':'Flags overlap; enriched checkpoints do not estimate prevalence. No outcome auditor was rerun or overruled.'}
    (R/'decision.json').write_text(json.dumps(decision,indent=2)+'\n')
    print(json.dumps(decision,indent=2))

if __name__=='__main__':main()
