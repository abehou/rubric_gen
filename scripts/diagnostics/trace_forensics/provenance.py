"""Read-only source, configuration, lineage, and recovery accounting."""
import hashlib,json,re,subprocess
from pathlib import Path
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from collect import ROOT,RUN,OUT,PUBLIC,read,write,sha,table,key,verdict


def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
commits={'original_user':git('rev-parse','0fbe0bb').decode().strip(),'original_full':git('rev-parse','314ea3d').decode().strip(),'checkpoint':git('rev-parse','73289de').decode().strip(),'investigation_head':git('rev-parse','HEAD').decode().strip()}
package_path=RUN/'diagnostics/runtime-validation-10382894/execution/manifest.json';package=read(package_path);package_root=Path(package['package_root'])
owners=[]
for p in sorted(RUN.glob('owners/candidate/*/launch.json')):
    d=read(p);out={k:v for k,v in d.items() if k!='source_hashes'}
    out.update(path=str(p),sha256=sha(p),recorded_config_hashes={k:v for k,v in d['source_hashes'].items() if k.endswith('.yaml') or k.endswith('runtime.json')})
    owners.append(out)
inventory=[];changed=[]
for rel,h in package['files'].items():
    assert sha(package_root/rel)==h,(rel,h)
    row=dict(path=rel,candidate_executed_sha256=h)
    for policy in ['original_user','original_full','checkpoint']:
        try:content=git('show',commits[policy]+':'+rel)
        except subprocess.CalledProcessError:content=None
        row[policy+'_sha256']=hashlib.sha256(content).hexdigest() if content is not None else None
    row['current_workspace_sha256']=sha(ROOT/rel) if (ROOT/rel).exists() else None
    inventory.append(row)
    if row['original_user_sha256']!=h:changed.append(rel)
table('source-hashes.csv',inventory)
for name,ref in [('original-user-to-checkpoint',commits['original_user']),('original-full-to-checkpoint',commits['original_full'])]:
    (PUBLIC/(name+'.diff')).write_bytes(git('diff',ref,commits['checkpoint'],'--','src/rubric_gen'))
initial=RUN/'owners/candidate/10381602-20260910T043109Z'
for filename in ['scientific.diff','implementation.diff']:
    if (initial/filename).exists():(PUBLIC/'candidate-launch.diff').write_bytes((initial/filename).read_bytes())
last=RUN/'owners/candidate/10382970-20260910T080302Z/implementation.diff'
(PUBLIC/'candidate-runtime-amendment.diff').write_bytes(last.read_bytes())
paths=sorted((OUT/'cases').glob('*.json'))
with ThreadPoolExecutor(max_workers=8) as pool:cases=list(pool.map(read,paths))
lookup={(c['policy'],c['setting'],c['task_id'],c['replicate']):c for c in cases}
fields=['benchmark','model','effective_solver_model','reasoning_effort','service_tier','judge_model','rubric_proposer_model','rubric_proposer_max_retries','feedback_policy','feedback_reference_protocol','feedback_simulator','prompt','prompt_implementation_sha256','review','max_review_chars','max_revisions','min_revisions','turn_timeout_seconds','command_network_access','web_search','isolation','elicitation_seed_replicates','seed_generator','red_team_generator','rubric_policy','initial_scoring_identity','instruction_sha256','data_sha256','master_rubric_sha256','initial_rubric_sha256','development_rubric_sha256','rubric_generation_implementation_sha256']
config_diffs=Counter();lineage=[];prompts=[];dedup=[]
for c in cases:
    root=Path(c['root'])
    for p in sorted((root/'red-team').glob('**/prompt.txt'))[:1]:
        normalized=re.sub(r'<active_rubric>.*?</active_rubric>','<active_rubric>\n{active_rubric}\n</active_rubric>',p.read_text(),flags=re.S)
        digest=hashlib.sha256(normalized.encode()).hexdigest()
        out=PUBLIC/'prompts'/f'{c["policy"]}-{digest[:12]}.txt';out.parent.mkdir(exist_ok=True);out.write_text(normalized)
        prompts.append(dict(case=key(c),source_path=str(p),source_sha256=sha(p),normalized_prompt_sha256=digest,normalized_file=str(out.relative_to(PUBLIC))))
    o=lookup.get(('original',c['setting'],c['task_id'],c['replicate']))
    if c['policy']=='candidate' and o:
        diff={k:dict(original=o['manifest'].get(k),candidate=c['manifest'].get(k)) for k in fields if o['manifest'].get(k)!=c['manifest'].get(k)}
        config_diffs.update(diff.keys())
        oldg=next(g for g in o['generations'] if g['generation']==1);newg=next(g for g in c['generations'] if g['generation']==1)
        oldx=o['checkpoints'][0];newx=c['checkpoints'][0]
        lineage.append(dict(setting=c['setting'],task_id=c['task_id'],replicate=c['replicate'],config_differences=diff,offline_criteria_equal=oldg['active_criteria']==newg['active_criteria'],offline_generation_hash_equal=oldg['generation_sha256']==newg['generation_sha256'],first_feedback_equal=oldx['feedback']==newx['feedback'],first_prompt_equal=oldx['prompt']==newx['prompt'],initial_submission_equal=o['rows'][0]['initial_submission_sha256']==c['rows'][0]['initial_submission_sha256'],selected_rubric_equal=o['rows'][0]['selected_rubric_sha256']==c['rows'][0]['selected_rubric_sha256']))
    # Reconstruct whether duplicate source/adversarial public-content pairs existed.
    pairs=[];artifact_sources={}
    for g in c['generations']:
        h=read(Path(g['path'])/'artifact-history.json')
        for a in h['artifacts']:
            artifact_sources[a['source_id']]=a['content_sha256']
    for p in sorted((root/'red-team').glob('**/manifest.json')):
        m=read(p)
        if m.get('included'):
            # Find the public artifact hash in native saved history, rather than
            # confusing the workspace hash (includes auxiliary files) with it.
            checkpoint=m['checkpoint']
            digest=artifact_sources.get(f'red-team:s{checkpoint:03d}')
            if digest:
                pairs.append(tuple(sorted([m['source_artifact_sha256'],digest])))
    dedup.append(dict(case=key(c),sidecars_with_hash_pair=len(pairs),duplicate_pairs=len(pairs)-len(set(pairs))))
table('lineage-config-comparison.csv',lineage);table('saved-prompt-provenance.csv',prompts);table('duplicate-sidecars.csv',dedup)
write(PUBLIC/'provenance.json',dict(commits=commits,execution_package=dict(path=str(package_path),sha256=sha(package_path)),owners=owners,executed_files_different_from_original_user=changed,matched_manifest_difference_counts=dict(config_diffs),representative_manifests={key(c):c['manifest'] for c in cases if c['task_id']=='da-12-2' and c['replicate']==1}))
before=read(RUN/'diagnostics/runtime-repair-before/receipt.json');first=read(RUN/'owners/candidate/10382423-20260910T061730Z/parent-study.json')
print('FIRST LEDGER KEYS',list(first))
preserved84={r['assignment_id'] for r in before['preserved_completions']}
for r in before['preserved_completions']:
    for f in r['files']:assert sha(f['path'])==f['sha256']
failed_file=next(RUN.glob('owners/candidate/10384474-*/before-detect-1/failures.json'));audit_failures=read(failed_file);audit_roots={r['source_path'] for r in audit_failures};failure_rows=[]
for c in cases:
    if c['policy']!='candidate':continue
    o=lookup.get(('original',c['setting'],c['task_id'],c['replicate']))
    oldpos=sum(verdict(r['direct']['full_trajectory'])=='positive' for r in o['rows']) if o else None
    newpos=sum(verdict(r['direct']['full_trajectory'])=='positive' for r in c['rows'])
    old_by_model={r['model']:r for r in o['rows']} if o else {}
    failure_rows.append(dict(setting=c['setting'],task_id=c['task_id'],replicate=c['replicate'],assignment_id=c['manifest']['assignment_id'],completed_before_final_runtime_repair=c['manifest']['assignment_id'] in preserved84,audit_only_recovery=c['root'] in audit_roots,original_positive_auditors=oldpos,candidate_positive_auditors=newpos,net_positive_change=newpos-oldpos if oldpos is not None else None,any_new_positive_auditor=any(verdict(n['direct']['full_trajectory'])=='positive' and verdict(old_by_model[n['model']]['direct']['full_trajectory'])!='positive' for n in c['rows']) if o else None))
table('recovery-overlap.csv',failure_rows);write(PUBLIC/'audit-recovery-failures.json',dict(path=str(failed_file),sha256=sha(failed_file),rows=audit_failures))
print('SOURCE CHANGES',changed);print('CONFIG DIFFS',config_diffs);print('LINEAGE', {f:sum(x[f] for x in lineage) for f in ['offline_criteria_equal','offline_generation_hash_equal','first_feedback_equal','first_prompt_equal','initial_submission_equal','selected_rubric_equal']});print('PROMPTS',len(prompts));print('DEDUP',sum(x['duplicate_pairs'] for x in dedup))
