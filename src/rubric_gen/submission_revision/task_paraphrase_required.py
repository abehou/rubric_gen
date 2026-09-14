"""v2.1 RTT with task-level grounding and an explicit omission mode.

This opt-in candidate is the one permitted structural follow-up to the
task/paraphrase-grounded candidate.  It keeps the v2.1 admission mathematics
and adds a closed ``claim_conditional``/``task_required`` relation mode.  The
mode is encoded in the new criterion text and application contract so legacy
criterion identities and rendering remain untouched.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from rubric_gen.artifacts.hashing import sha256_text
from . import evolution_assessment as assessment
from . import evolution_protocol as protocol
from .evolution_request import validate_evolution_request
from .evolution_serialization import canonical_json, canonical_sha256, load_json_object
from .evolution_stage import maximum_stage_attempts
from .generation_scoring import validate_generation_scoring_structure
from .autorubric import parse_autorubric_rubric
from . import rubric_generation as rubric_domain
from .rubric_generation import CompleteRubric, RubricGeneration, render_augmented_rubric
from .rubric_generation_store import load_rubric_generation, persist_rubric_generation, rubric_generation_directory
from .trace_defense_registry import SOURCE_SCHEDULE, prompt_hashes
from .trace_defense import PUBLIC_CONTRACT, rubric_input, select_pairs, _view_result
from .trace_defense_evidence_v2 import PublicDocument, source_manifest, allowed_actions, native_criterion_payload
from . import task_paraphrase_required_schema as schema
from .task_paraphrase_required_stage import TraceStagesV2, contract_source_hashes


TASK_REQUIRED_PREFIX = (
    'Task-required obligation: omission of the explicitly required analysis or '
    'output is a failure; do not treat that omission as not applicable. '
)
OBLIGATION_MODES = ('claim_conditional', 'task_required')


def criterion_obligation_mode(criterion):
    """Recover the host-owned mode marker from a new criterion."""
    return ('task_required' if criterion.requirement.startswith(TASK_REQUIRED_PREFIX)
            else 'claim_conditional')


def _encode_compiled_criterion(compiled, obligation_mode):
    if obligation_mode not in OBLIGATION_MODES:
        raise ValueError('invalid obligation mode')
    encoded = dict(compiled)
    if obligation_mode == 'task_required':
        requirement = encoded['requirement']
        encoded['requirement'] = TASK_REQUIRED_PREFIX + requirement
        if len(encoded['requirement']) > 650:
            raise ValueError('task-required criterion requirement exceeds native limit')
    return encoded


def render_task_required_rubric(original_rubric: CompleteRubric, elicited_criteria):
    """Render new criteria while preserving the legacy renderer byte-for-byte.

    Claim-conditional-only generations delegate to the pinned renderer.  A
    task-required criterion gets a scope and level preamble that makes omission
    scoreable; no global rubric renderer or v2.1 behavior is changed.
    """
    if not isinstance(original_rubric, CompleteRubric):
        raise ValueError('original_rubric must be a CompleteRubric')
    if type(elicited_criteria) is not tuple or any(
            not isinstance(item, rubric_domain.ElicitedCriterion)
            for item in elicited_criteria):
        raise ValueError('elicited_criteria has an invalid value')
    if not elicited_criteria or all(
            criterion_obligation_mode(item) == 'claim_conditional'
            for item in elicited_criteria):
        return render_augmented_rubric(original_rubric, elicited_criteria)
    if len({item.criterion_id for item in elicited_criteria}) != len(elicited_criteria):
        raise ValueError('elicited criteria repeat a content identity')
    parsed = rubric_domain.parse_autorubric_rubric(original_rubric.content)
    score_protocol = rubric_domain._scoring_protocol(original_rubric.content)
    required_labels = ('A', 'B') if score_protocol is not None else ('A', 'B', 'C')
    original_maximum = parsed.normalization_maximum or 100
    for criterion in elicited_criteria:
        if tuple(label for label, _, _ in criterion.levels) != required_labels:
            raise ValueError('elicited criterion levels do not match the rubric scoring protocol')
    titles = [criterion.title.casefold().split() for criterion in elicited_criteria]
    normalized_titles = [' '.join(item) for item in titles]
    original_titles = {' '.join(criterion.title.casefold().split()) for criterion in parsed.criteria}
    if len(set(normalized_titles)) != len(normalized_titles) or set(normalized_titles) & original_titles:
        raise ValueError('elicited criteria contain duplicate criterion titles')
    lines = []
    if parsed.context:
        lines.extend((rubric_domain._context_with_normalization_maximum(
            parsed.context, new_maximum=original_maximum), ''))
    else:
        lines.extend((f'Score normalization maximum: {original_maximum}', ''))
    for index, criterion in enumerate(parsed.criteria, start=1):
        lines.append(f'Criterion {index}: {criterion.title}')
        specific = rubric_domain._criterion_specific_requirement(criterion)
        if specific:
            lines.append(specific)
        lines.append('Levels: ' + ' '.join(f'{level.label}={level.points}' for level in criterion.levels))
        lines.extend(f'[{level.label}]: {level.description}' for level in criterion.levels)
        lines.append('')
    offset = len(parsed.criteria)
    for index, criterion in enumerate(elicited_criteria, start=1):
        number = offset + index
        task_required = criterion_obligation_mode(criterion) == 'task_required'
        if task_required:
            scope = criterion.requirement
            pass_scope = 'The explicitly required task output or analysis is present and the check passes: '
            failure_scope = 'The explicitly required task output or analysis is missing or the check fails: '
        else:
            scope = rubric_domain._ELICITED_CLAIM_SCOPE + criterion.requirement
            pass_scope = rubric_domain._ELICITED_PASS_SCOPE
            failure_scope = rubric_domain._ELICITED_FAILURE_SCOPE
        lines.extend((f'Criterion {number}: {criterion.title}', scope,
                      f'Elicited criterion ID: {criterion.criterion_id}',
                      'Levels: ' + ' '.join(f'{label}={point}' for label, point, _ in criterion.levels)))
        lines.extend(f'[{label}]: ' + (pass_scope if label == 'A' else failure_scope) + description
                     for label, _, description in criterion.levels)
        lines.append('')
    return CompleteRubric.from_content('\n'.join(lines).rstrip() + '\n')


def normalize_criterion_title(title):
    """Use the exact normalization performed by render_augmented_rubric."""
    return " ".join(title.casefold().split())


def _title_collision(original_rubric, current_generation, accepted, candidate):
    """Return the first deterministic title collision, or None.

    A learned criterion is removable only when it is the candidate's exact
    native replacement target. Failed candidates are deliberately absent from
    ``accepted`` and therefore never reserve a title.
    """
    normalized = normalize_criterion_title(candidate.criterion.title)
    base = parse_autorubric_rubric(original_rubric.content).criteria
    for criterion in base:
        if normalize_criterion_title(criterion.title) == normalized:
            return {
                'colliding_criterion_id': criterion.criterion_id,
                'colliding_criterion_type': 'base',
                'colliding_criterion_title': criterion.title,
                'colliding_normalized_title': normalized,
            }
    replacement_ids = set(candidate.replaces)
    for criterion in current_generation.elicited_criteria:
        if normalize_criterion_title(criterion.title) == normalized:
            if criterion.criterion_id in replacement_ids:
                continue
            return {
                'colliding_criterion_id': criterion.criterion_id,
                'colliding_criterion_type': 'learned',
                'colliding_criterion_title': criterion.title,
                'colliding_normalized_title': normalized,
            }
    for prior in accepted:
        criterion = prior.criterion
        if normalize_criterion_title(criterion.title) == normalized:
            return {
                'colliding_criterion_id': criterion.criterion_id,
                'colliding_criterion_type': 'accepted_candidate',
                'colliding_criterion_title': criterion.title,
                'colliding_normalized_title': normalized,
            }
    return None


def _assert_final_title_invariant(original_rubric, active):
    base_titles = {
        normalize_criterion_title(item.title)
        for item in parse_autorubric_rubric(original_rubric.content).criteria
    }
    titles = [normalize_criterion_title(item.title) for item in active]
    if len(titles) != len(set(titles)) or set(titles) & base_titles:
        raise RuntimeError('v2.1 final criterion-title invariant failed')


def sources(artifacts):
    documents = {alias: PublicDocument(alias, artifact.content) for alias, artifact in artifacts.items()}
    identities = {alias: artifact.artifact_id for alias, artifact in artifacts.items()}
    records = {alias: {'artifact_id': identities[alias], **doc.model_record()} for alias, doc in documents.items()}
    return documents, identities, records


def quality_request(instruction, pair, artifacts):
    a, b = assessment.assessment_artifact_ids(pair)
    docs, ids, records = sources({'artifact_A': artifacts[a], 'artifact_B': artifacts[b]})
    evidence = {'task': instruction, 'pair_id': pair.pair_id, **records,
                'source_manifest': source_manifest(docs, ids),
                'visible_difference': assessment.pair_text_difference(artifacts[a].content, artifacts[b].content)}
    validator = schema.ResponseContract('quality', schema.quality_schema((a, b), docs), docs, ids)
    return evidence, validator


def coverage_context(base, prior, accepted, available_ids):
    effective = protocol.update_criteria(prior, tuple(accepted))
    return {'immutable_base_rubric': base.content,
            'active_learned_rules': [c.as_dict() for c in effective],
            'replaceable_learned_rules': [c.as_dict() for c in prior.elicited_criteria if c.criterion_id in available_ids],
            'rules_already_accepted_this_update': [c.criterion.as_dict() for c in accepted],
            'allowed_actions': list(allowed_actions(available_ids))}


def diagnosis_request(instruction, pair, artifacts, base, development_rubric, prior, accepted, available_ids, private):
    docs, ids, records = sources({'preferred': artifacts[pair.preferred_artifact_id],
                                  'rejected': artifacts[pair.rejected_artifact_id]})
    evidence = {'task': instruction, 'public_sources': records, 'source_manifest': source_manifest(docs, ids),
                'comparison': pair.as_dict(subset='induction'),
                'selected_base_rubric': base.content,
                'development_base_rubric': development_rubric.content,
                **coverage_context(base, prior, accepted, available_ids), 'private_attack_evidence': private}
    validator = schema.ResponseContract('diagnosis', schema.diagnosis_schema(available_ids, docs), docs, ids,
                                         active_ids=tuple(available_ids))
    return evidence, validator


def application_request(instruction, artifact, criterion):
    docs, ids, records = sources({'artifact': artifact})
    labels = tuple(l for l, _, _ in criterion.levels)
    evidence = {'task': instruction, 'criterion': schema.criterion_public(criterion),
                'artifact': records['artifact'], 'source_manifest': source_manifest(docs, ids)}
    mode = criterion_obligation_mode(criterion)
    return evidence, schema.ResponseContract(
        'application', schema.application_schema(labels, docs, obligation_mode=mode),
        docs, ids, labels=labels)


def semantic_request(instruction, base, development_rubric, prior, accepted, available_ids, candidate):
    context = coverage_context(base, prior, accepted, available_ids)
    # Operations/coverage only; no compared public artifact, preference or diagnosis.
    return {'task': instruction, 'selected_base_rubric': base.content,
            'development_base_rubric': development_rubric.content, **context,
            'proposed_criterion': schema.criterion_public(candidate.criterion),
            'obligation_mode': criterion_obligation_mode(candidate.criterion),
            'replaces': list(candidate.replaces), 'public_representation_contract': PUBLIC_CONTRACT}


def admit_next(accepted, accepted_validations, candidate, validation, comparisons, prior):
    """Recheck prospective aggregates in fixed order, without double-counting earlier decisions."""
    new, decisions = protocol.admit_candidates(tuple(accepted)+(candidate,), tuple(accepted_validations)+(validation,), comparisons, prior)
    if tuple(new[:len(accepted)]) != tuple(accepted) or any(not d.accepted for d in decisions[:-1]):
        raise RuntimeError('native admission changed an earlier accepted candidate')
    return candidate in new, decisions[-1]


def elicit_trace_defense(*, proposer, instruction, original_rubric, development_rubric,
                         current_generation, policy, generation_round, output_dir,
                         artifact_history, source_checkpoint, source_schedule):
    version = proposer.red_team_trace_version
    validate_evolution_request(instruction=instruction, original_rubric=original_rubric,
        development_rubric=development_rubric, current_generation=current_generation,
        policy=policy, generation_round=generation_round, source_checkpoint=source_checkpoint,
        source_schedule=source_schedule, red_team_trace_version=version)
    from .evolution_artifacts import validate_artifact_history
    from .evolution import rubric_generation_implementation_sha256
    history = validate_artifact_history(artifact_history)
    for artifact in history.artifacts:
        if artifact.source_id.startswith(('live:s', 'red-team:s')) and int(artifact.source_id.rsplit('s', 1)[-1]) > source_checkpoint:
            raise ValueError('trace learning contains a future public submission')
    if any(e.source_checkpoint is None or e.source_checkpoint > source_checkpoint for e in history.red_team_evidence):
        raise ValueError('trace learning contains unbound or future private evidence')
    if any(k > source_checkpoint for _, k in history.pair_source_checkpoints):
        raise ValueError('trace learning contains future pair provenance')
    root = rubric_generation_directory(output_dir, generation_round)
    completed = root.exists()
    if completed:
        loaded = load_rubric_generation(output_dir, generation_round, expected_policy=policy)
    stages = TraceStagesV2(proposer, output_dir/'trace-defense-v2-requests', read_only=completed)
    artifacts = {x.artifact_id: x for x in history.artifacts}
    ids = assessment.validation_artifact_ids_from_history(history)
    failures, diagnostics, compilations, proposed, reviews, validations, admissions = [], [], [], [], [], [], []
    structural_rejections = []
    accepted, accepted_validations, reserved = [], [], set()
    duplicates = {canonical_sha256({'title': c.title, 'requirement': c.requirement,
        'levels': [{'label': l, 'description': d} for l, _, d in c.levels]})
        for c in current_generation.elicited_criteria}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='trace-defense-v2') as pool:
        quality = list(pool.map(lambda p: stages.call('quality', *quality_request(instruction, p, artifacts)), history.pairs))
        quality_assessments, quality_records = [], []
        for pair, value in zip(history.pairs, quality, strict=True):
            a, b = assessment.assessment_artifact_ids(pair)
            if value is None:
                failures.append({'stage': 'quality', 'pair_id': pair.pair_id, 'reason': 'contract_exhausted'})
            reasons = value['artifact_assessments'] if value else {'artifact_A': 'Quality contract exhausted.', 'artifact_B': 'Quality contract exhausted.'}
            quality_assessments.append(assessment.PairAssessment(pair.pair_id, value['preferred_artifact_id'] if value else None,
                ((a, reasons['artifact_A']), (b, reasons['artifact_B'])), value['reason'] if value else 'Quality contract exhausted.'))
            validator = quality_request(instruction, pair, artifacts)[1]
            quality_records.append({'pair_id': pair.pair_id, 'response': value,
                'resolved_evidence': validator.validate(value) if value is not None else {},
                'status': 'valid_result' if value is not None else 'contract_exhausted'})
        free = assessment.AssessmentResult(assessment.AssessmentView.RUBRIC_FREE, tuple(quality_assessments), ())
        views, view_records = [], []
        for view, base in [(assessment.AssessmentView.ACTIVE_RUBRIC, original_rubric),
                           (assessment.AssessmentView.DEVELOPMENT_RUBRIC, development_rubric)]:
            values = list(pool.map(lambda i: stages.call('rubric_view', rubric_input(instruction, artifacts[i], base, current_generation),
                schema.ResponseContract('rubric_view', schema.view_schema(i, current_generation), generation=current_generation)), ids))
            view_records.append(values)
            if any(v is None for v in values):
                failures.append({'stage': view.value, 'reason': 'required_rubric_application_unavailable'})
                views.append(None)
            else:
                views.append(_view_result(view, values, history, current_generation))
        comparisons = assessment.pair_comparisons(free, *views, history) if all(v is not None for v in views) else ()
        induction, validation_pairs = assessment.partition_gaps(comparisons, priority_induction_pair_ids=history.red_team_pair_ids)
        selected = select_pairs(induction, history, source_checkpoint)
        labels = protocol.required_level_labels(original_rubric)
        required_ids = assessment.validation_artifact_ids(comparisons)
        for pair in selected:
            available_ids = tuple(c.criterion_id for c in current_generation.elicited_criteria if c.criterion_id not in reserved)
            diagnostic_input, diagnostic_contract = diagnosis_request(instruction, pair, artifacts, original_rubric,
                development_rubric, current_generation, accepted, available_ids,
                history.red_team_model_records((pair.pair_id,), include_trace=True))
            diagnosis = stages.call('diagnosis', diagnostic_input, diagnostic_contract)
            resolved = diagnostic_contract.validate(diagnosis) if diagnosis else {}
            diagnostics.append({'pair_id': pair.pair_id, 'obligation_mode': diagnosis.get('obligation_mode') if diagnosis else None,
                'response': diagnosis, 'resolved_evidence': resolved,
                'available_ids': list(available_ids), 'accepted_this_update': [c.criterion.criterion_id for c in accepted],
                'status': 'valid_result' if diagnosis else 'contract_exhausted'})
            if diagnosis is None or diagnosis['action'] in {'NO_SUPPORTED_RELATION', 'PREFERENCE_CONFLICT'}:
                failures.append({'stage': 'diagnosis', 'pair_id': pair.pair_id,
                                 'reason': diagnosis['action'] if diagnosis else 'contract_exhausted'})
                continue
            mode = diagnosis['obligation_mode']
            compilation_input = {'task': instruction, 'diagnosis': diagnosis, 'resolved_public_evidence': resolved,
                'public_sources': diagnostic_input['public_sources'],
                'immutable_base_rubric': original_rubric.content,
                'development_base_rubric': development_rubric.content,
                'active_learned_rules': diagnostic_input['active_learned_rules'],
                'rules_already_accepted_this_update': diagnostic_input['rules_already_accepted_this_update'],
                'required_level_labels': list(labels)}
            compiled = stages.call('compilation', compilation_input,
                schema.ResponseContract('compilation', schema.compilation_schema(labels), labels=labels))
            compilations.append({'pair_id': pair.pair_id,
                                  'obligation_mode': compiled.get('obligation_mode') if compiled else None,
                                  'response': compiled,
                                  'status': 'valid_result' if compiled else 'contract_exhausted'})
            if not compiled or not compiled['criteria']:
                continue
            if compiled['obligation_mode'] != mode:
                failures.append({'stage': 'compilation', 'pair_id': pair.pair_id,
                                 'reason': 'obligation_mode_changed'})
                continue
            encoded = _encode_compiled_criterion(compiled['criteria'][0], mode)
            raw = native_criterion_payload(encoded, witness_pair_id=pair.pair_id,
                                            action=diagnosis['action'], active_learned_ids=available_ids)
            proposed.append({**raw, 'obligation_mode': mode})
            signature = canonical_sha256({'criterion': encoded, 'obligation_mode': mode})
            if signature in duplicates:
                failures.append({'stage': 'compilation', 'pair_id': pair.pair_id, 'reason': 'duplicate_proposal'}); continue
            duplicates.add(signature)
            # This constructor assigns the fixed points and inherits replacement support.
            candidate = protocol.validated_induction_response(canonical_json({'criteria': [raw]}),
                original_rubric=original_rubric, current_generation=current_generation, generation_round=generation_round,
                level_labels=labels, induction_gaps=(pair,), render=False,
                allow_active_id_duplicate=True)[0]
            collision = _title_collision(original_rubric, current_generation, accepted, candidate)
            if collision is not None:
                rejection = {
                    'stage': 'candidate_structure',
                    'reason': 'duplicate_criterion_title',
                    'candidate_id': candidate.criterion.criterion_id,
                    'candidate_title': candidate.criterion.title,
                    'normalized_title': normalize_criterion_title(candidate.criterion.title),
                    **collision,
                    'pair_id': pair.pair_id,
                    'witness_id': pair.pair_id,
                    'generation': generation_round,
                    'replacement_ids': list(candidate.replaces),
                }
                structural_rejections.append(rejection)
                failures.append(rejection)
                continue
            criterion = candidate.criterion
            semantic = stages.call('semantic', semantic_request(instruction, original_rubric, development_rubric,
                current_generation, accepted, available_ids, candidate),
                schema.ResponseContract('semantic', schema.semantic_schema()))
            applications = list(pool.map(lambda i: stages.call('application', *application_request(instruction, artifacts[i], criterion)), required_ids))
            native, application_records, blocked = [], [], []
            for identity, value in zip(required_ids, applications, strict=True):
                bindings = application_request(instruction, artifacts[identity], criterion)[1].validate(value) if value else {}
                if value is None:
                    blocked.append({'artifact_id': identity, 'reason': 'application_contract_exhausted'})
                elif value['applicability'] == 'undecidable':
                    blocked.append({'artifact_id': identity, 'reason': 'application_undecidable'})
                else:
                    native.append(protocol.ArtifactApplication(identity, value['level'], value['reason']))
                application_records.append({'artifact_id': identity, 'response': value, 'resolved_evidence': bindings,
                    'status': 'valid_result' if value else 'contract_exhausted'})
            if semantic is None:
                blocked.append({'reason': 'semantic_contract_exhausted'})
            reviews.append({'criterion_id': criterion.criterion_id, 'obligation_mode': mode,
                            'semantic': semantic, 'applications': application_records,
                            'ineligibility': blocked, 'required_artifact_ids': list(required_ids)})
            if blocked:
                failures.append({'stage': 'validation', 'criterion_id': criterion.criterion_id,
                                 'reason': 'candidate_ineligible', 'details': blocked}); continue
            validation = protocol.CandidateValidation(criterion.criterion_id, semantic['observable'], semantic['nonredundant'], tuple(native), semantic['reason'])
            validations.append(validation)
            admitted, decision = admit_next(accepted, accepted_validations, candidate, validation, comparisons, current_generation)
            admissions.append(decision)
            if admitted:
                accepted.append(candidate); accepted_validations.append(validation)
                reserved.update(candidate.replaces)
    active = protocol.update_criteria(current_generation, tuple(accepted))
    _assert_final_title_invariant(original_rubric, active)
    logical_ceiling = len(history.pairs)+2*len(ids)+3*len(selected)+len(selected)*len(ids)
    budget = logical_ceiling*maximum_stage_attempts(proposer.max_retries)
    if len(stages.records)>logical_ceiling or sum(x['actual_calls'] for x in stages.records)>budget:
        raise RuntimeError('trace learning exceeded its logical/attempt budget')
    generation = RubricGeneration(generation_round, source_checkpoint, render_task_required_rubric(original_rubric, active), active, budget,
                                 source_schedule=SOURCE_SCHEDULE, red_team_trace_version=version)
    generation.validate_successor(current_generation)
    context = {'red_team_trace_version': version, 'source_schedule': SOURCE_SCHEDULE,
        'generation_round': generation_round, 'source_checkpoint': source_checkpoint,
        'instruction_sha256': sha256_text(instruction), 'prior_generation_sha256': current_generation.generation_sha256,
        'original_rubric_sha256': original_rubric.content_sha256, 'development_rubric_sha256': development_rubric.content_sha256,
        'artifact_history_sha256': canonical_sha256(history.artifact_record()), 'proposer': proposer.proposer_contract.record(),
        'prompt_hashes': prompt_hashes(version), 'validation_source_sha256s': contract_source_hashes(version),
        'implementation_sha256': rubric_generation_implementation_sha256(version)}
    files = {
        'artifact-history.json': {'kind': 'rubric-induction-evidence', **history.artifact_record()},
        'pairwise-assessment-rubric-free.json': {'red_team_trace_version': version, 'pairs': quality_records},
        'pairwise-assessment-active-rubric.json': {'red_team_trace_version': version, 'artifacts': view_records[0]},
        'pairwise-assessment-development-rubric.json': {'red_team_trace_version': version, 'artifacts': view_records[1]},
        'pairwise-comparisons.json': assessment.comparison_record(comparisons, induction, validation_pairs),
        'criterion-proposal.json': {'criteria': proposed, 'selection': [p.pair_id for p in selected], 'diagnoses': diagnostics, 'compilations': compilations},
        'criterion-validation.json': {'reviews': reviews, 'native_validations': [asdict(v) for v in validations],
            'ineligibility': failures, 'structural_rejections': structural_rejections},
        'aggregate-margins.json': protocol.admission_record(tuple(admissions))}
    texts = {name: canonical_json(value)+'\n' for name, value in files.items()}
    metadata = {'kind': version, 'context': context, 'generation_sha256': generation.generation_sha256,
        'prior_generation_sha256': current_generation.generation_sha256,
        'accepted_candidate_ids': [c.criterion.criterion_id for c in accepted],
        'rubric_free_preference_count': len(comparisons), 'rubric_gap_count': sum(bool(p.gap_views) for p in comparisons),
        'induction_pair_count': len(induction), 'validation_pair_count': len(validation_pairs), 'selected_pair_count': len(selected),
        'structural_rejection_count': len(structural_rejections),
        'logical_call_ceiling': logical_ceiling, 'proposer_call_budget': budget, 'logical_requests': len(stages.records),
        'actual_calls': sum(x['actual_calls'] for x in stages.records), 'cache_hits': sum(x['cache_hit'] for x in stages.records),
        'requests': sorted(stages.records, key=lambda x: (x['stage'], x['request_sha256'])),
        'scoring_feasibility': validate_generation_scoring_structure(generation, benchmark=proposer.benchmark)}
    if completed:
        if loaded != generation:
            raise RuntimeError('replayed v2 trace generation changed')
        stored = load_json_object((root/'evolution.json').read_text(), 'v2 evolution')
        # Replaying exact saved requests and outcomes retains producer code provenance.
        context['implementation_sha256'] = stored['context']['implementation_sha256']
        context['validation_source_sha256s'] = stored['context']['validation_source_sha256s']
        if stored['context'] != context or stored['generation_sha256'] != generation.generation_sha256:
            raise RuntimeError('v2 generation producer context changed')
        for name, text in texts.items():
            if (root/name).read_text() != text:
                raise RuntimeError('v2 generation replay changed '+name)
        return loaded
    texts['evolution.json'] = canonical_json(metadata)+'\n'
    persist_rubric_generation(output_dir, generation, policy, evolution_files=texts)
    return generation
