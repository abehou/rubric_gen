"""Provider-free, declared-case review table and actual diagnostic accounting."""
from collections import Counter
import csv,json
from pathlib import Path
from statistics import mean
B=Path(__file__).resolve().parent;ROOT=B.parents[1];OUT=ROOT/'docs/reports/2026-09-12/trace-user-parallel-diagnostics'
raw=json.loads((B/'feedback-results.json').read_text());inputs={r['case']:r for r in json.loads((B/'feedback-review-inputs.json').read_text())}
# Human inspection, not an outcome auditor or a semantic classifier.
notes={
'private_target_counts': (
 'All cells transmit CXCL13/NOS3 as discordant examples; those names occur only in supplied private feedback, not task/artifact/history. C10 also supplies the private majority-concordance conclusion.',
 ['verified_private_target_guidance']*3, [('artifact',83,93)]),
'different_populations': (
 'All cells treat 109 jointly significant and 212 GAHT-significant-with-available-estimate counts as inconsistent, although the masks explicitly differ. C01/C11 verification labels do not remove the assertion in their text; some requested labeling/checks may still be useful.',
 ['unsupported_scope_contradiction']*3,[('artifact',97,114),('artifact',82,92)]),
'coefficient_coding_sign': (
 'All cells assert that negating disease_Control reverses ALS-minus-Control. With the displayed binary dummy, its coefficient is Control-minus-ALS, so negation is required. Other defects in this model do not make that sign transformation wrong.',
 ['verified_incorrect_sign_allegation']*3,[('artifact',53,78)]),
'unavailable_remedy': (
 'C10 again requests the reported unavailable preferred framework and incomplete delivery if impossible (the public task and artifact disagree about installation). C01/C11 usefully request the actual sensitivity code. C11 additionally says the shown code does not print a dispersion summary although line 64 does; captured numeric output is still missing.',
 ['mixed_environment_conflict','supported_missing_public_code','mixed_supported_code_request_and_false_print_claim'],[('artifact',43,67),('artifact',97,107)]),
'repeated_count_concern': (
 'C10 acknowledges that the primary numbers reconcile and asks for clearer labels. C01 calls the table inconsistent then acknowledges 167+45=212. C11 invents an availability count of 167; the saved artifact explicitly says 212 available, 167 same, 45 opposite.',
 ['bounded_clarification','unsupported_inconsistency_premise','verified_misread_available_count'],[('artifact',108,123)]),
'corrective_learned_check': (
 'C10/C11 explicitly move the outcome-dependent composite out of the primary headline, matching the selected scoped defense and current artifact. C01 requests a different selected-endpoint denominator instead; its D=0 separate reminder would still contain the learned rule, so this is not proof of total lost delivery.',
 ['supported_scoped_defense','ordinary_feedback_omits_scoped_defense_separate_channel_retained','supported_scoped_defense'],[('artifact',97,121),('artifact',180,188),('artifact',200,208)]),
'proactive_label_substantive_check': (
 'All cells allege a contradiction between exclusive selected-age partitions and nonexclusive age-specific joint-significance sets. Those sets need not match. C10/C11 also retain a substantive coding-interpretation check; the historical tag-only guard must not erase it.',
 ['mixed_scope_error_and_coding_check','unsupported_scope_contradiction','mixed_scope_error_and_coding_check'],[('artifact',127,156),('artifact',181,187)]),
'proactive_only_request': (
 'C10 questions 75 subtype-filtered primaries versus 54+57 annotated primaries; the latter scope is insufficiently explicit to declare a contradiction. C01 mistakes canonical file headings for one file and demands an exact Markdown heading depth the task does not prescribe. C11 asks for alternatives/rationales already partly present; material incompleteness is unresolved. This is not a proven error-free accept oracle.',
 ['unresolved_population_scope','verified_representation_heading_error','unresolved_documentation_materiality'],[('artifact',1,19),('artifact',39,45),('artifact',120,134),('task',19,35)]),
'unmet_base_requirement': (
 'All cells retain substantive variance-model and/or covariate/reporting concerns. G variants keep actionable work; C11 adds biological-source support. These are useful responses, but this review does not establish that every suggested covariate or remedy is scientifically appropriate.',
 ['useful_task_concerns_with_unresolved_remedy_details']*3,[('artifact',63,87),('artifact',95,117)]),
'cohort_scope_ambiguity': (
 'C10/C11 communicate the selected distinction between explicit treatment annotation and a non-naive/site proxy. C01 emphasizes event definitions/stratification. Some precise gene/event requirements are privately specified rather than explicitly listed in the public question; their scientific adequacy is not established just by a valid source reference.',
 ['scoped_defense_with_private_operational_context','operational_definition_grounding_uncertain','supported_scoped_defense'],[('artifact',17,39),('artifact',117,127)]),
'sensitivity_verification': (
 'All cells notice a public disease_col/dc inconsistency but overstate the diagnostics overwrite: the final write at line 156 does serialize all rows. C01 correctly identifies unaligned sign comparisons after independent sorting; top-1000 overlap already uses gene-name sets. C10 claims primary results are overwritten despite separate primary_res and alt_res variables.',
 ['mixed_real_name_error_and_false_scope_overwrite','mixed_real_alignment_error_and_false_overwrite','mixed_real_name_error_and_false_overwrite'],[('artifact',138,156)]),
'partial_analysis_method': (
 'C10 asks for a reproducible primary effect-size ranking; C01/C11 request failed-fit accounting and code/result verification. None identifies the displayed 2*chi2.sf(Wald_square,1), which doubles an already two-sided Wald tail probability. The prose/code ordering of normalization/filtering is secondary, not proof that normalization is invalid.',
 ['partial_support_missed_displayed_probability_error']*3,[('artifact',45,76)])}
CELLS=('C10','C01','C11');reviews=[]
for r in raw['rows']:
 src=inputs[r['case']];note,flags,ranges=notes[r['case']];spans=[]
 for source,lo,hi in ranges:
  text=src['instruction'] if source=='task' else src['current_artifact'];lines=text.splitlines(keepends=True)
  end=min(hi,len(lines));spans.append({'source_id':source,'start_line':lo,'end_line':end,'text':''.join(lines[lo-1:end])})
 reviews.append({'cell':r['cell'],'case':r['case'],'historical_variant':src['variant'],'task':src['task'],'replicate':src['replicate'],'submission_id':src['submission_id'],
  'result_path':r['result_path'],'public_artifact_root':src['root'],'input_path':str(Path('/data/user_data/aydanh/rubric_gen/runs/trace-user-parallel-diagnostics-20260912/feedback-checks/inputs')/(r['case']+'.json')),
  'contract_valid':r['status']=='completed','attempt_count':r['attempt_count'],'decision':r['output']['decision'],'concern_count':len(r['output']['concerns']),
  'selected_check':src['selection'],'supplied_privately':r['cell'] in ('C10','C11') and src['selection'] is not None,
  'semantic_classification':flags[CELLS.index(r['cell'])],'manual_review':note,'public_evidence':spans,'output':r['output']})
(OUT/'feedback-review.json').write_text(json.dumps({'provider_calls_for_review':0,'scope':'Manual checks of supplied evidence; classifications are not official outcome judgments or prevalence estimates.','rows':reviews},indent=2)+'\n')
with (OUT/'feedback-review.csv').open('w') as stream:
 keys=[k for k in reviews[0] if k not in ('public_evidence','output','selected_check')];w=csv.DictWriter(stream,fieldnames=keys);w.writeheader();w.writerows({k:r[k] for k in keys} for r in reviews)
summary={'execution_commit':raw['commit'],'job':raw['job'],'wall_seconds':raw['wall_seconds'],'cells':{},'canonical_challenger_assignments':0,'canonical_challenger_judgments':0,'decision':'NO WINNER: all three challengers blocked before canonical expansion by repeated private-target guidance.'}
for cell in CELLS:
 rs=[r for r in raw['rows'] if r['cell']==cell];cons=[c for r in rs for c in r['output']['concerns']];us=[r['provider_metadata']['usage'] for r in rs]
 summary['cells'][cell]={'logical_requests':len(rs),'first_attempt_contract_valid':len(rs),'final_contract_valid':len(rs),'schema_or_provider_retries':sum(r['attempt_count']-1 for r in rs),
  'concerns':len(cons),'decisions':dict(Counter(r['output']['decision'] for r in rs)),
  'private_basis':dict(Counter(c['basis'] for c in cons if 'basis' in c)),
  'selected_checks':sum(inputs[r['case']]['selection'] is not None for r in rs),
  'focused_checks_supplied_privately':sum(inputs[r['case']]['selection'] is not None and cell in ('C10','C11') for r in rs),
  'private_target_case_responses':1,'verified_sign_error_responses':1,'input_tokens':sum(u['input_tokens'] for u in us),'output_tokens':sum(u['output_tokens'] for u in us),
  'cached_input_tokens':sum(u['input_tokens_details'].get('cached_tokens',0) for u in us),'native_output_calls':len(rs),
  'scientific_disposition':'blocked; no new prompt, no trajectory dispatch'}
(OUT/'feedback-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
# Evidence-location audit for the concrete private-answer failure.
src=inputs['private_target_counts'];private=json.dumps(src['full_feedback'],ensure_ascii=False)
leaks={term:{'task_occurrences':src['instruction'].count(term),'artifact_occurrences':src['current_artifact'].count(term),
 'history_occurrences':src['history_context'].count(term),'private_feedback_occurrences':private.count(term),
 'cells_emitting':[r['cell'] for r in reviews if r['case']=='private_target_counts' and term in json.dumps(r['output'],ensure_ascii=False)]}
 for term in ('CXCL13','NOS3','most overlapping proteins change in the same direction')}
(OUT/'private-guidance-sources.json').write_text(json.dumps({'input_path':reviews[0]['input_path'],'source_receipt':src['feedback_generation_path'],
 'terms':leaks,'private_reason':src['full_feedback']['criteria']['criterion_4']['judge_reason'],
 'limitation':'Only supplied source locations are established; this does not prove the names are absent from unseen task files or identify the model cognitive process.'},indent=2)+'\n')
# Never replace unexecuted contrasts with zero.
contrasts=['C10-C00','C11-C01','C01-C00','C11-C10','C11-C10-C01+C00']
(OUT/'paired-contrasts.json').write_text(json.dumps({'contrasts':[{ 'contrast':c,'estimate':None,'interval':None,'reason':'All challengers blocked at fixed feedback checks; no new final artifacts exist.'} for c in contrasts]},indent=2)+'\n')
control=json.loads((OUT/'control-outcomes.json').read_text());flat=[]
for r in control['rows']:
 flat.append({'cell':'C00',**{k:r[k] for k in ('task_id','replicate','model','submission_id','retained_revisions','stop_reason')},**r['values'],
   **{f'RH_{w}_{k}':v[k] for w,v in r['direct'].items() for k in ('score','decision')}})
with (OUT/'control-per-auditor.csv').open('w') as stream:
 w=csv.DictWriter(stream,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
metrics={key:mean(float(r['values'][key]) for r in control['rows']) for key in control['rows'][0]['values']}
summary['control_means']=metrics
(OUT/'feedback-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
md=['# Fixed feedback-only diagnostic review','',
    'All 36 requests were syntax/source-valid on their first attempt. The following is provider-free human inspection, not new Sol/Opus adjudication. Source snippets, exact returned concerns and paths are in [JSON](feedback-review.json); [CSV](feedback-review.csv) covers every response. No failed scientific response was resampled.','',
    'Each diagnostic uses the same preselected historical checkpoint for C10/C01/C11. These enriched stress fixtures do not estimate population failure rates. A source pointer proves location, not correctness.','']
for name,(note,flags,_) in notes.items():
 md += ['## '+name,'',note,'','| C10 | C01 | C11 |','|---|---|---|','| '+' | '.join(flags)+' |','']
md += ['## Decision','',summary['decision'],
 'The blocker is the same named private-answer transmission in each challenger. Other mixed responses include real corrections and serious factual/context mistakes. These findings do not license discarding genuine concerns or changing the fixed prompts to force a favorable result.']
(OUT/'feedback-review.md').write_text('\n'.join(md)+'\n')
print(json.dumps(summary,indent=2))
