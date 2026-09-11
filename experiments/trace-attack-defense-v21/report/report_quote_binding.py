"""Read saved exact-quote failures; text normalizations are diagnostics, never repairs."""
import json,os,re,unicodedata
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path
from report_sources import RUN,OUT,PUBLIC,read,write,sha
from report_pipeline import table
from rubric_gen.submission_revision.trace_defense_schema import bind_quotes


def whitespace(value):
 return ' '.join(value.split())

def markup(value):
 return whitespace(re.sub(r'(?m)^\s*#{1,6}\s+', '',value).replace('**','').replace('__','').replace('`',''))

def typography(value):
 return markup(unicodedata.normalize('NFKC',value).translate(str.maketrans({'“':'"','”':'"','‘':"'",'’':"'",'–':'-','—':'-','×':'x','−':'-'})))

def ordered_ellipsis_fragments(quote,content,transform=lambda x:x):
 fragments=[transform(x.strip()) for x in re.split(r'\.{3,}|…',quote) if x.strip()]
 if len(fragments)<2:return False
 target=transform(content);offset=0
 for fragment in fragments:
  found=target.find(fragment,offset)
  if found<0:return False
  offset=found+len(fragment)
 return True

def category(quote,content,others=()):
 if not isinstance(quote,str) or not quote:return 'missing_or_empty_quote'
 if quote in content:return 'exact_match_UNEXPECTED'
 if any(quote in other for other in others):return 'literal_in_other_displayed_artifact'
 if whitespace(quote) in whitespace(content):return 'whitespace_only_match'
 if markup(quote) in markup(content):return 'markup_and_whitespace_match'
 if typography(quote) in typography(content):return 'typography_markup_whitespace_match'
 if quote in json.dumps(content,ensure_ascii=False)[1:-1]:return 'json_escaped_representation_match'
 if ordered_ellipsis_fragments(quote,content):return 'ellipsis_joined_ordered_public_spans'
 if ordered_ellipsis_fragments(quote,content,markup):return 'ellipsis_plus_markup_whitespace'
 return 'no_match_under_diagnostic_transforms'


def inspect(root):
 manifest=read(root/'manifest.json');base={k:manifest[k] for k in ('assignment_id','task_id','replicate','condition_id')};base['arm']='user' if base['condition_id'].startswith('user') else 'full'
 requests=[];quotes=[]
 for p in sorted((root/'trace-defense-requests').glob('*/result.json')):
  receipt=read(p);request=receipt['request'];stage=request['stage']
  if stage not in ('quality','diagnosis','application'):continue
  evidence=json.loads(request['evidence']);value=receipt['outcome']['value']
  if value is None:continue
  if stage=='quality':
   arts=[evidence['artifact_A'],evidence['artifact_B']];items=value['decisive_evidence'];required=[a['artifact_id'] for a in arts] if value['preferred_artifact_id'] else []
  elif stage=='diagnosis':
   arts=evidence['artifacts'];items=value['preferred_evidence']+value['rejected_evidence'];required=[a['artifact_id'] for a in arts] if value['status']=='supported_relation' else []
  else:arts=[evidence['artifact']];items=value['public_evidence'];required=[]
  public={a['artifact_id']:a['content'] for a in arts}
  _,errors=bind_quotes(items,public,required_ids=required)
  row={**base,'stage':stage,'request_sha256':p.parent.name,'quoted_spans':len(items),'invalid_spans':sum(e['reason']=='quote_not_in_named_artifact' for e in errors),'missing_required_witnesses':sum(e['reason']=='missing_required_public_witness' for e in errors),'any_source_failure':bool(errors),'path':str(p),'sha256':sha(p)}
  if stage=='diagnosis':
   allowed={c['criterion_id'] for c in evidence['current_criteria']};replaces=value['replaces']
   row.update(invalid_diagnosis_replacement=len(set(replaces))!=len(replaces) or any(x not in allowed for x in replaces),
    diagnosis_replacement_scope_mismatch=(value['gap_cause']=='refine_existing')!=bool(replaces),
    supplied_active_ids=sorted(allowed),returned_replaces=replaces,gap_cause=value['gap_cause'],diagnosis_status=value['status'])
  requests.append(row)
  for error in errors:
   if error['reason']!='quote_not_in_named_artifact':continue
   identity=error['artifact_id'];quote=error.get('quote');content=public.get(identity,'')
   label=category(quote,content,[v for k,v in public.items() if k!=identity]);assert label!='exact_match_UNEXPECTED'
   quotes.append({**base,'stage':stage,'request_sha256':p.parent.name,'artifact_id':identity,'quote':quote,'category':label,'artifact_sha256':__import__('hashlib').sha256(content.encode()).hexdigest(),'request_path':str(p),'request_file_sha256':row['sha256']})
 return requests,quotes


def main():
 assert os.environ.get('SLURM_JOB_ID')
 studies=list((RUN/'study').glob('*/study.json'));assert len(studies)==1
 ledger=read(studies[0]);chosen=[r for r in ledger['records'] if r['condition_id'].endswith('red-team-trace')]
 assert len(chosen)==120 and all(r['status']=='completed' for r in chosen)
 with ThreadPoolExecutor(max_workers=4) as pool:data=list(pool.map(inspect,[studies[0].parent/r['experiment_dir'] for r in chosen]))
 requests=[r for a,b in data for r in a];quotes=[r for a,b in data for r in b]
 summary={}
 for arm in ('full','user'):
  summary[arm]={}
  for stage in ('quality','diagnosis','application'):
   rs=[r for r in requests if r['arm']==arm and r['stage']==stage];qs=[q for q in quotes if q['arm']==arm and q['stage']==stage]
   summary[arm][stage]={'unique_assignment_cache_entries':len(rs),'entries_with_source_failure':sum(r['any_source_failure'] for r in rs),'quoted_spans':sum(r['quoted_spans'] for r in rs),'invalid_spans':len(qs),'missing_required_witnesses':sum(r['missing_required_witnesses'] for r in rs),'diagnostic_categories':dict(Counter(q['category'] for q in qs))}
   if stage=='diagnosis':
    summary[arm][stage].update({k:sum(r[k] for r in rs) for k in ('invalid_diagnosis_replacement','diagnosis_replacement_scope_mismatch')})
 samples=[];taken=Counter()
 for q in quotes:
  key=q['arm'],q['stage'],q['category']
  if taken[key]>=2:continue
  taken[key]+=1;value=read(q['request_path']);ev=json.loads(value['request']['evidence']);arts=[ev[k] for k in ('artifact_A','artifact_B','artifact') if k in ev]+ev.get('artifacts',[])
  content=next(a['content'] for a in arts if a['artifact_id']==q['artifact_id'])
  match=SequenceMatcher(None,q['quote'],content,autojunk=False).find_longest_match()
  samples.append({**q,'longest_exact_subspan_length':match.size,'nearby_public_text':content[max(0,match.b-160):min(len(content),match.b+match.size+200)],'nearby_text_is_not_a_corrected_quote':True})
 table('quote-binding-requests.csv',requests,large=True);table('quote-binding-failed-spans.csv',quotes,large=True)
 write(PUBLIC/'quote-binding-summary.json',{'summary':summary,'counting_unit':'one completed assignment-local exact request-cache entry, not repeated generation references','diagnostic_only':'Normalization categories do not make a quotation valid, verify its meaning, alter a verdict, or change the executed admission policy. All native literal failures remain failures.','source_sha256':sha(__file__)})
 write(PUBLIC/'quote-binding-examples.json',samples)
 replacement_samples=[]
 for arm in ('full','user'):
  replacement_samples.extend([r for r in requests if r['arm']==arm and r.get('invalid_diagnosis_replacement')][:4])
 write(PUBLIC/'diagnosis-replacement-examples.json',replacement_samples)
 print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
