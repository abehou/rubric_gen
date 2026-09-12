"""One admitted-rule reminder, separate from ordinary feedback generation."""
import re
from dataclasses import replace
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from .artifacts import read_json_object
from .feedback import FeedbackPolicy, _validate_score_record
from .trace_defense_prompts import CORRECTIVE, ANTICIPATORY

_NUMERIC = re.compile(r'(?<![\w.])[+-]?(?:\d+(?:,\d{3})*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?')

def numeric_literals(text):
    return set(_NUMERIC.findall(text))


def select_reminder(*,generation,score_validation_path,root,submission_id,instruction):
    checkpoint=int(submission_id[1:])
    record_dir=root/'trace-defense-reminders'
    prior_records=[read_json_object(record_dir/f's{i:03d}.json','prior trace reminder') for i in range(checkpoint)]
    reminded={r['selection']['criterion_id'] for r in prior_records if r['selection'] is not None}
    validation=read_json_object(score_validation_path,'score validation')
    _,_,_,scores=_validate_score_record(validation,generation.rubric.content,generation.rubric.content_sha256)
    offset=len(scores)-len(generation.elicited_criteria)+1
    task_numbers=numeric_literals(instruction)
    eligible=[]; skipped=[]
    for index,c in enumerate(generation.elicited_criteria,offset):
        points=scores[f'criterion_{index}']
        new=c.source_generation==generation.generation_round
        category=(1 if new and points<0 else 2 if points<0 else 3 if new and c.criterion_id not in reminded
                  else 4 if checkpoint==0 and c.source_generation==1 and c.criterion_id not in reminded else None)
        if category is None:continue
        reason=None
        if len(c.requirement)>650:reason='requirement_exceeds_delivery_limit'
        extra=sorted(numeric_literals(c.requirement)-task_numbers)
        if extra:reason='numeric_literal_absent_from_public_task'
        if reason:
            skipped.append({'criterion_id':c.criterion_id,'reason':reason,'absent_numeric_literals':extra});continue
        eligible.append((category,points,-c.source_generation,c.criterion_id,c))
    eligible.sort(key=lambda x:x[:4])
    selection=None
    if eligible:
        category,points,_,identity,c=eligible[0]
        corrective=points<0
        selection={'criterion_id':identity,'source_generation':c.source_generation,'category':category,
                   'points':points,'previously_reminded':identity in reminded,'corrective':corrective,
                   'requirement':c.requirement}
    return selection, skipped


def appendix_mode(version, feedback_policy):
    """User-only v2.1 ablations; selection and all other feedback are unchanged."""
    if FeedbackPolicy(feedback_policy) is FeedbackPolicy.USER_SIMULATOR:
        return {
            'attack_defense_v2.1_corrective_appendix': 'corrective_only',
            'attack_defense_v2.1_no_appendix': 'none',
        }.get(version, 'legacy')
    return 'legacy'


def append_reminder(projected,*,generation,score_validation_path,root,submission_id,instruction,allow_generation,
                    delivery_mode='legacy'):
    if delivery_mode not in {'legacy', 'corrective_only', 'none'}:
        raise ValueError('unknown trace appendix delivery mode')
    selection, skipped = select_reminder(generation=generation,
        score_validation_path=score_validation_path, root=root,
        submission_id=submission_id, instruction=instruction)
    checkpoint=int(submission_id[1:])
    record_dir=root/'trace-defense-reminders'
    block='' if selection is None else (CORRECTIVE if selection['corrective'] else ANTICIPATORY).format(
        admitted_requirement=selection['requirement'])
    suppressed = bool(selection) and (delivery_mode == 'none'
        or (delivery_mode == 'corrective_only' and not selection['corrective']))
    if suppressed:
        block = ''
    prompt=projected.prompt+('\n\n'+block if block else '')
    record={'red_team_trace_version':generation.red_team_trace_version,'submission_id':submission_id,'solver_turn':checkpoint+1,
            'generation_sha256':generation.generation_sha256,'selection':selection,'skipped':skipped,
            'message_component':block,'ordinary_prompt_sha256':sha256_text(projected.prompt),
            'final_prompt_sha256':sha256_text(prompt)}
    if delivery_mode != 'legacy':
        # select_reminder deliberately reads *selection*, not delivery: a
        # suppressed passing selection still occupies its legacy history slot.
        record.update(appendix_policy=delivery_mode, appendix_emitted=bool(block),
                      appendix_suppressed=suppressed)
    path=record_dir/f'{submission_id}.json'
    if path.exists():
        if read_json_object(path,'trace reminder')!=record:
            raise RuntimeError('persisted trace reminder changed')
    elif allow_generation:write_json_atomic(path,record)
    else:raise RuntimeError('trace reminder receipt missing')
    return replace(projected,prompt=prompt)
