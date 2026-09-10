"""Explicit submission/rubric bindings for the pre-revision schedule."""
from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks import get_submission_benchmark
from .artifacts import read_json_object
from .evolution_serialization import canonical_sha256
from .rubric_generation import RubricPolicy
from .rubric_generation_store import load_rubric_generation, rubric_generation_directory
from .trace_defense_prompts import VERSION, SOURCE_SCHEDULE, enabled, prompt_hashes


def method_identity(policy,version):
    if not enabled(policy,version):
        return {}
    return {'red_team_trace_version':VERSION,'source_schedule':SOURCE_SCHEDULE,
            'trace_defense_prompt_hashes':prompt_hashes()}


def _public_sha(root,submission_id,benchmark):
    return sha256_text(get_submission_benchmark(benchmark).render_user_review(root/'submissions'/submission_id/'workspace'))


def persist_binding(root,submission_id,generation,*,feedback_opportunity,benchmark):
    checkpoint=int(submission_id[1:])
    if generation.source_schedule!=SOURCE_SCHEDULE or generation.red_team_trace_version!=VERSION:
        raise RuntimeError('new trace scoring requires a versioned generation')
    if feedback_opportunity:
        if generation.source_checkpoint!=checkpoint:
            raise RuntimeError('feedback update must use exactly its current sealed submission')
    else:
        previous=load_binding(root,f's{checkpoint-1:03d}',benchmark=benchmark)
        if previous['active_generation_sha256']!=generation.generation_sha256:
            raise RuntimeError('terminal scoring must retain the last active generation')
    body={'red_team_trace_version':VERSION,'source_schedule':SOURCE_SCHEDULE,
          'submission_id':submission_id,'submission_public_sha256':_public_sha(root,submission_id,benchmark),
          'active_generation_round':generation.generation_round,
          'active_generation_sha256':generation.generation_sha256,
          'source_checkpoint':generation.source_checkpoint,
          'source_evidence_sha256':sha256_file(rubric_generation_directory(root,generation.generation_round)/'artifact-history.json'),
          'feedback_opportunity':feedback_opportunity,'solver_turn':checkpoint+1 if feedback_opportunity else None}
    record={**body,'binding_sha256':canonical_sha256(body)}
    path=root/'submission-rubric-bindings'/f'{submission_id}.json'
    if path.exists():
        if read_json_object(path,'submission/rubric binding')!=record:
            raise RuntimeError('submission/rubric binding changed')
    else:write_json_atomic(path,record)
    return record


def load_binding(root,submission_id,*,benchmark=None):
    record=read_json_object(root/'submission-rubric-bindings'/f'{submission_id}.json','submission/rubric binding')
    if benchmark is None:
        benchmark=read_json_object(root/'manifest.json','revision manifest')['benchmark']
    body={k:v for k,v in record.items() if k!='binding_sha256'}
    if record.get('binding_sha256')!=canonical_sha256(body) or record.get('submission_id')!=submission_id:
        raise RuntimeError('invalid submission/rubric binding hash or ID')
    if record.get('red_team_trace_version')!=VERSION or record.get('source_schedule')!=SOURCE_SCHEDULE:
        raise RuntimeError('invalid submission/rubric binding recipe')
    generation=load_rubric_generation(root,record['active_generation_round'],expected_policy=RubricPolicy.RED_TEAM_TRACE)
    if generation.source_schedule!=SOURCE_SCHEDULE or generation.generation_sha256!=record['active_generation_sha256']:
        raise RuntimeError('binding identifies an incompatible active generation')
    if _public_sha(root,submission_id,benchmark)!=record['submission_public_sha256']:
        raise RuntimeError('bound public submission changed')
    if sha256_file(rubric_generation_directory(root,generation.generation_round)/'artifact-history.json')!=record['source_evidence_sha256']:
        raise RuntimeError('bound source evidence changed')
    checkpoint=int(submission_id[1:])
    if record['source_checkpoint']!=generation.source_checkpoint or generation.source_checkpoint>checkpoint:
        raise RuntimeError('binding contains future or incorrect source evidence')
    if type(record['feedback_opportunity']) is not bool:
        raise RuntimeError('binding feedback opportunity is invalid')
    if record['feedback_opportunity']:
        if record['source_checkpoint']!=checkpoint or record['solver_turn']!=checkpoint+1:
            raise RuntimeError('binding does not precede its next solver turn')
    else:
        prior=load_binding(root,f's{checkpoint-1:03d}',benchmark=benchmark)
        if record['solver_turn'] is not None or record['active_generation_sha256']!=prior['active_generation_sha256']:
            raise RuntimeError('terminal binding changed its active generation')
    return record
