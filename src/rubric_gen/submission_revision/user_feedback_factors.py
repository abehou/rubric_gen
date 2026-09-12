"""Two explicit User-only factors; the v2.1 learner and selector are shared.

Private evidence addresses locate sources, not scientific truth. No analytical
field changes the simulator's decision or removes a substantive concern.
"""
from copy import deepcopy
from dataclasses import replace

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from .artifacts import read_json_object
from .evolution_serialization import canonical_json
from .trace_defense_delivery import select_reminder
from .trace_defense_evidence_v2 import PublicDocument, references_schema, bind_references

# C00 is the existing attack_defense_v2.1, without a new alias.
VARIANTS = {
    'attack_defense_user_d1g0': (True, False),
    'attack_defense_user_d0g1': (False, True),
    'attack_defense_user_d1g1': (True, True),
}

DELIVERY = """An optional focused_dynamic_check is provided as private review context. Assess it together with the current public artifact and ordinary evaluator feedback. When it identifies an actual unresolved problem, incorporate the relevant corrective action within your existing maximum of three concerns. Do not add a separate concern outside that budget. A nonviolated proactive check alone is not a reason to request revision. Do not give the check automatic priority over a more material current task defect. Do not expose its private metadata."""

GROUNDING = """Before requesting a revision, check the proposed concern against the CURRENT public task and artifact. Private evaluator feedback identifies issues to investigate; it is not proof that a claim or method is wrong. Distinguish an observed defect, an unresolved verification question, and an unmet task requirement. State an error as established only when the visible evidence supports it; otherwise ask for the specific check needed without assuming the answer.

Check that compared quantities refer to the same entities, population, method, units and stage of analysis before calling them inconsistent. Reconcile the latest artifact with prior feedback before repeating a concern. Do not demand a resolved correction unless you identify what remains wrong now.

Repair the specific invalid or unsupported operation. Preserve independently supported findings, not numbers merely because they already exist or satisfy a rubric. Keeping invalid inference and adding a caveat is not a correction; deleting an entire analysis is not automatically a correction either. Ask for the smallest scientifically justified repair and identify the remaining uncertainty.

Recommend remedies compatible with the information available about the task environment. An unavailable preferred package alone does not establish impossibility or validate an approximate replacement. Do not repeatedly demand an unavailable remedy without new evidence of feasibility. Do not assert that an unseen file is absent or that an unobserved execution failed.

Never provide an expected numerical result, count, ranking or substantive conclusion derived only from private evaluator feedback. Request a calculation or verification from public inputs without supplying the private answer, even approximately or conditionally. Public task thresholds and publicly reported artifact values can be discussed when their source is clear. Do not ask the solver to reproduce a hidden target or claim a rerun that the public evidence does not support.

Prioritize the material current problems supported by this review, within the existing three-concern limit. If no material problem remains, accept."""

REFERENCE_FORMAT = """For each concern, include private basis (observed_defect, verification_request, or task_requirement) and compact public_refs to the supplied numbered task/current-artifact sources. Cite source_id and inclusive start_line/end_line, using separate ranges for separate passages. These fields are analysis metadata, not solver instructions. Valid addresses do not prove the interpretation."""
BASES = ('observed_defect', 'verification_request', 'task_requirement')


def budgeted(version):
    return VARIANTS.get(version, (False, False))[0]


def public_documents(instruction, current_artifact):
    return {'task': PublicDocument('task', instruction),
            'artifact': PublicDocument('artifact', current_artifact)}


def focused_check(selection, generation):
    if selection is None:
        return None
    return {'mode': 'corrective' if selection['corrective'] else 'proactive',
            'requirement': selection['requirement'],
            'newly_admitted': selection['source_generation'] == generation.generation_round,
            'currently_violated': selection['corrective']}


def feedback_request(*, trace_version, focused_dynamic_check=None, **kwargs):
    from .user_simulator import _feedback_request
    delivery, grounded = VARIANTS[trace_version]
    if not delivery and focused_dynamic_check is not None:
        raise ValueError('separate delivery must not expose its selection to the simulator')
    request = _feedback_request(**kwargs)
    instructions, evidence, schema = request.instructions, request.evidence, deepcopy(request.schema)
    if delivery and focused_dynamic_check is not None:
        instructions += '\n\n' + DELIVERY
        evidence += '\n<focused_dynamic_check>\n' + canonical_json(focused_dynamic_check) + '\n</focused_dynamic_check>\n'
    if grounded:
        instructions += '\n\n' + GROUNDING + '\n\n' + REFERENCE_FORMAT
        docs = public_documents(kwargs['instruction'], kwargs['current_artifact'])
        # Replace only the two public blocks with address layers over the exact
        # same bytes. Private feedback/history are unchanged; no new evidence.
        for tag, alias, content in (('task_instruction', 'task', kwargs['instruction']),
                                    ('current_artifact', 'artifact', kwargs['current_artifact'])):
            block = '<' + tag + '>\n' + content + '\n</' + tag + '>'
            evidence = evidence.replace(block, '<' + tag + '>\n' + canonical_json(docs[alias].model_record()) + '\n</' + tag + '>', 1)
        item = schema['properties']['concerns']['items']
        item['required'] += ['basis', 'public_refs']
        item['properties']['basis'] = {'type': 'string', 'enum': list(BASES)}
        refs = references_schema(docs)
        refs['minItems'] = 1
        item['properties']['public_refs'] = refs
    return replace(request, instructions=instructions, evidence=evidence, schema=schema,
                   schema_name=(request.schema_name if not grounded else 'submission_simulated_user_feedback_grounded'))


def solver_feedback(value):
    """Remove only declared private fields, never edit text or accept/revise."""
    return {'decision': value['decision'], 'concerns': [
        {'category': c['category'], 'feedback': c['feedback']} for c in value['concerns']]}


def validate_output(value, *, trace_version, instruction, current_artifact, max_concerns):
    from .user_simulator import _validate_feedback_output
    if not VARIANTS[trace_version][1]:
        return _validate_feedback_output(value, max_concerns=max_concerns)
    if type(value) is not dict or set(value) != {'decision', 'concerns'} or type(value['concerns']) is not list:
        raise ValueError('grounded feedback has invalid decision/concerns fields')
    docs = public_documents(instruction, current_artifact)
    for c in value['concerns']:
        if type(c) is not dict or set(c) != {'category', 'feedback', 'basis', 'public_refs'}:
            raise ValueError('grounded concern has invalid fields')
        if c['basis'] not in BASES or not c['public_refs']:
            raise ValueError('grounded concern requires a legal basis and public references')
        bind_references(c['public_refs'], docs)
    ordinary = _validate_feedback_output(solver_feedback(value), max_concerns=max_concerns)
    return {'decision': ordinary['decision'], 'concerns': [
        {**c, 'basis': original['basis'], 'public_refs': original['public_refs']}
        for c, original in zip(ordinary['concerns'], value['concerns'], strict=True)]}


def source_bindings(value, *, instruction, current_artifact):
    docs = public_documents(instruction, current_artifact)
    return [bind_references(c['public_refs'], docs) for c in value['concerns']]


def persist_budget_delivery(*, root, submission_id, generation, selection, skipped,
                            prompt, user_feedback, allow_generation):
    """Record what is known. Neither tags nor concern count establish exposure."""
    record = {'red_team_trace_version': generation.red_team_trace_version,
              'submission_id': submission_id, 'solver_turn': int(submission_id[1:]) + 1,
              'generation_sha256': generation.generation_sha256,
              'delivery_mode': 'user_simulator_budget', 'selection': selection,
              'skipped': skipped, 'focused_dynamic_check': focused_check(selection, generation),
              'message_component': '', 'ordinary_prompt_sha256': sha256_text(prompt),
              'final_prompt_sha256': sha256_text(prompt),
              'model_declared_association': 'unknown',
              'semantic_exposure': 'unknown', 'omission_reason': 'unknown',
              'rendered_feedback': solver_feedback(user_feedback)}
    path = root/'trace-defense-reminders'/f'{submission_id}.json'
    if path.exists():
        if read_json_object(path, 'budgeted delivery') != record:
            raise RuntimeError('persisted budgeted delivery changed')
    elif allow_generation:
        write_json_atomic(path, record)
    else:
        raise RuntimeError('budgeted delivery receipt missing')
