"""The explicit attack_defense_v1 learning pipeline; native admission is unchanged."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from rubric_gen.artifacts.hashing import sha256_text
from . import evolution_assessment as assessment
from . import evolution_protocol as protocol
from .evolution_request import validate_evolution_request
from .evolution_serialization import canonical_json, canonical_sha256, load_json_object
from .evolution_stage import maximum_stage_attempts
from .generation_scoring import validate_generation_scoring_structure
from .rubric_generation import RubricGeneration, render_augmented_rubric
from .rubric_generation_store import load_rubric_generation, persist_rubric_generation, rubric_generation_directory
from .trace_defense_prompts import VERSION, SOURCE_SCHEDULE, prompt_hashes
from . import trace_defense_schema as schema
from .trace_defense_stage import TraceStages

PUBLIC_CONTRACT = ('Only canonical submitted public material is inspected. Private workspace files, '
                   'execution history, hidden targets, attack roles, and outcome judgments are unavailable.')


def quality_input(instruction, pair, artifacts):
    a, b = assessment.assessment_artifact_ids(pair)
    return {'task':instruction, 'pair_id':pair.pair_id,
            'artifact_A':artifacts[a].model_record(), 'artifact_B':artifacts[b].model_record(),
            'visible_difference':assessment.pair_text_difference(artifacts[a].content,artifacts[b].content)}


def rubric_input(instruction, artifact, base, generation):
    return {'task':instruction, 'artifact':artifact.model_record(), 'base_rubric':base.content,
            'active_penalty_criteria':[{'criterion_id':c.criterion_id, **schema.criterion_public(c)}
                                       for c in generation.elicited_criteria],
            'score_minimum':0, 'score_maximum':generation.normalization_maximum}


def application_input(instruction, artifact, criterion):
    return {'task':instruction, 'criterion':schema.criterion_public(criterion),
            'artifact':artifact.model_record()}


def semantic_input(instruction, base, generation, candidate):
    return {'task':instruction, 'base_rubric':base.content,
            'current_criteria':[{'criterion_id':c.criterion_id, **schema.criterion_public(c)}
                                for c in generation.elicited_criteria],
            'proposed_criterion':schema.criterion_public(candidate.criterion),
            'replaces':list(candidate.replaces), 'public_representation_contract':PUBLIC_CONTRACT}


def _pair_checkpoint(pair, history):
    if pair.pair_id in dict(history.pair_source_checkpoints):
        return dict(history.pair_source_checkpoints)[pair.pair_id]
    private = [e.source_checkpoint for e in history.red_team_evidence
               if e.pair_id==pair.pair_id and e.source_checkpoint is not None]
    if private:
        return max(private)
    ids = {pair.preferred_artifact_id,pair.rejected_artifact_id}
    return max((int(a.source_id.rsplit('s',1)[-1]) for a in history.artifacts
                if a.artifact_id in ids and a.source_id.startswith('live:s')), default=-1)


def select_pairs(induction, history, checkpoint):
    by_id = {p.pair_id:p for p in induction}
    newest = sorted(e.pair_id for e in history.red_team_evidence
                    if e.source_checkpoint==checkpoint and e.pair_id in by_id)
    if history.newest_sidecar_pair_id in by_id:
        newest = [history.newest_sidecar_pair_id]
    chosen = [by_id[newest[0]]] if newest else []
    def key(p):
        margins=[]
        for view in p.gap_views:
            scores = p.active_rubric_scores if view is assessment.AssessmentView.ACTIVE_RUBRIC else p.development_rubric_scores
            margins.append(scores[0].total_score-scores[1].total_score)
        return (min(margins),-_pair_checkpoint(p,history),p.pair_id)
    for pair in sorted(induction,key=key):
        if pair not in chosen and len(chosen)<2:
            chosen.append(pair)
    return tuple(chosen)


def _validate_view(value,generation):
    expected = {c.criterion_id:c for c in generation.elicited_criteria}
    levels=value['criterion_levels']
    if len({x['criterion_id'] for x in levels}) != len(levels) or {x['criterion_id'] for x in levels} != set(expected):
        raise ValueError('rubric view must apply every active criterion exactly once')
    for x in levels:
        if x['level'] not in {l for l,_,_ in expected[x['criterion_id']].levels}:
            raise ValueError('criterion level outside supplied scale')


def _view_result(view,raws,history,generation):
    scores=[]
    for raw in raws:
        levels={x['criterion_id']:x['level'] for x in raw['criterion_levels']}
        penalty=sum(next(p for l,p,_ in c.levels if l==levels[c.criterion_id]) for c in generation.elicited_criteria)
        scores.append(assessment.RubricScore(raw['artifact_id'],raw['base_score'],
                      tuple((c.criterion_id,levels[c.criterion_id]) for c in generation.elicited_criteria),
                      max(0,raw['base_score']+penalty),raw['reason']))
    by_id={x.artifact_id:x for x in scores}
    pairs=[]
    for pair in history.pairs:
        a,b=pair.artifact_ids
        preferred=a if by_id[a].total_score>by_id[b].total_score else b if by_id[b].total_score>by_id[a].total_score else None
        pairs.append(assessment.PairAssessment(pair.pair_id,preferred,
                      ((a,by_id[a].reason),(b,by_id[b].reason)), 'Preference computed from independent scores.'))
    return assessment.AssessmentResult(view,tuple(pairs),tuple(scores))


def _compile_validation(value, labels):
    if not value['criteria']:
        if value['predicted_levels'] is not None:
            raise ValueError('empty compilation requires null predicted_levels')
        return
    if value['predicted_levels'] is None:
        raise ValueError('criterion requires diagnostic predicted levels')
    raw=value['criteria'][0]
    from .evolution_artifacts import single_line
    single_line(raw['requirement'],'new criterion requirement',650)
    if tuple(x['label'] for x in raw['levels']) != labels:
        raise ValueError('criterion levels must follow supplied order')
    for level in raw['levels']:
        single_line(level['description'],'new level description',500)


def elicit_trace_defense(*,proposer,instruction,original_rubric,development_rubric,
                         current_generation,policy,generation_round,output_dir,
                         artifact_history,source_checkpoint,source_schedule):
    validate_evolution_request(instruction=instruction,original_rubric=original_rubric,
        development_rubric=development_rubric,current_generation=current_generation,
        policy=policy,generation_round=generation_round,source_checkpoint=source_checkpoint,
        source_schedule=source_schedule,red_team_trace_version=VERSION)
    from .evolution_artifacts import validate_artifact_history
    from .evolution import rubric_generation_implementation_sha256
    history=validate_artifact_history(artifact_history)
    for artifact in history.artifacts:
        if artifact.source_id.startswith(("live:s", "red-team:s")):
            if int(artifact.source_id.rsplit("s", 1)[-1]) > source_checkpoint:
                raise ValueError("trace learning contains a future public submission")
    if any(e.source_checkpoint is None or e.source_checkpoint > source_checkpoint for e in history.red_team_evidence):
        raise ValueError("trace learning contains unbound or future private evidence")
    if any(k > source_checkpoint for _, k in history.pair_source_checkpoints):
        raise ValueError("trace learning contains future pair provenance")
    root=rubric_generation_directory(output_dir,generation_round)
    completed=root.exists()
    if completed:
        loaded=load_rubric_generation(output_dir,generation_round,expected_policy=policy)
    stages=TraceStages(proposer,output_dir/'trace-defense-requests',read_only=completed)
    artifacts={x.artifact_id:x for x in history.artifacts}
    ids=assessment.validation_artifact_ids_from_history(history)
    public={i:artifacts[i].content for i in ids}
    failures=[]
    with ThreadPoolExecutor(max_workers=4,thread_name_prefix='trace-defense') as pool:
        quality=list(pool.map(lambda p:stages.call('quality',quality_input(instruction,p,artifacts),
                    schema.quality_schema(assessment.assessment_artifact_ids(p))),history.pairs))
        quality_assessments=[]; quality_records=[]
        for pair,value in zip(history.pairs,quality,strict=True):
            resolved,errors=([],[]) if value is None else schema.bind_quotes(value['decisive_evidence'],
                {i:public[i] for i in pair.artifact_ids},
                required_ids=pair.artifact_ids if value['preferred_artifact_id'] else ())
            preferred=None if value is None or errors else value['preferred_artifact_id']
            if value is None or errors:
                failures.append({'stage':'quality','pair_id':pair.pair_id,'reason':'source_failure' if errors else 'response_unavailable','errors':errors})
            reasons={i:'Quality assessment unavailable.' for i in pair.artifact_ids} if value is None else value['artifact_assessments']
            quality_assessments.append(assessment.PairAssessment(pair.pair_id,preferred,
                tuple((i,reasons[i]) for i in assessment.assessment_artifact_ids(pair)),
                value['reason'] if value else 'Quality assessment unavailable.'))
            quality_records.append({'pair_id':pair.pair_id,'response':value,'resolved_evidence':resolved,'source_errors':errors})
        free=assessment.AssessmentResult(assessment.AssessmentView.RUBRIC_FREE,tuple(quality_assessments),())
        views=[]; view_records=[]
        for view,base in [(assessment.AssessmentView.ACTIVE_RUBRIC,original_rubric),
                          (assessment.AssessmentView.DEVELOPMENT_RUBRIC,development_rubric)]:
            values=list(pool.map(lambda i: stages.call('rubric_view',rubric_input(instruction,artifacts[i],base,current_generation),
                           schema.view_schema(i,current_generation),lambda v:_validate_view(v,current_generation)),ids))
            view_records.append(values)
            if any(v is None for v in values):
                failures.append({'stage':view.value,'reason':'required_rubric_application_unavailable'})
                views.append(None)
            else:
                views.append(_view_result(view,values,history,current_generation))
        # Incomplete required views block the entire learning update; never drop a protected pair.
        comparisons=assessment.pair_comparisons(free,*views,history) if all(v is not None for v in views) else ()
        induction,validation=assessment.partition_gaps(comparisons,priority_induction_pair_ids=history.red_team_pair_ids)
        selected=select_pairs(induction,history,source_checkpoint)
        labels=protocol.required_level_labels(original_rubric)
        diagnostics=[]; compilations=[]; candidates=[]; proposed=[]; occupied=set(); duplicate=set()
        for pair in selected:
            pair_public={i:public[i] for i in (pair.preferred_artifact_id,pair.rejected_artifact_id)}
            private=history.red_team_model_records((pair.pair_id,),include_trace=True)
            diagnostic_input={'task':instruction,'artifacts':[artifacts[i].model_record() for i in pair_public],
                              'comparison':pair.as_dict(subset='induction'), 'current_rubric':current_generation.rubric.content,
                              'current_criteria':[c.as_dict() for c in current_generation.elicited_criteria],
                              'private_attack_evidence':private}
            value=stages.call('diagnosis',diagnostic_input,schema.diagnosis_schema(pair,current_generation))
            errors=[]; resolved=[]
            if value:
                for field,identity in [('preferred_evidence',pair.preferred_artifact_id),('rejected_evidence',pair.rejected_artifact_id)]:
                    bound,bad=schema.bind_quotes(value[field],{identity:public[identity]},
                        required_ids=(identity,) if value['status']=='supported_relation' else ())
                    resolved+=bound; errors+=bad
                if len(set(value['replaces']))!=len(value['replaces']) or any(x not in {c.criterion_id for c in current_generation.elicited_criteria} for x in value['replaces']):
                    errors.append({'reason':'invalid_diagnosis_replacement'})
                if (value['gap_cause']=='refine_existing') != bool(value['replaces']):
                    errors.append({'reason':'diagnosis_replacement_scope_mismatch'})
            diagnostics.append({'pair_id':pair.pair_id,'response':value,'resolved_evidence':resolved,'source_errors':errors})
            if not value or errors or value['status']!='supported_relation':
                failures.append({'stage':'diagnosis','pair_id':pair.pair_id,
                                 'reason':'source_failure' if errors else value['status'] if value else 'response_unavailable','errors':errors})
                continue
            compilation_input={'task':instruction,'diagnosis':value,
                               'artifacts':[artifacts[i].model_record() for i in pair_public],
                               'current_criteria':[c.as_dict() for c in current_generation.elicited_criteria],
                               'fixed_levels':[{'label':l,'points':p} for l,p in zip(labels,protocol.fixed_penalty_points(labels,current_generation.normalization_maximum),strict=True)],
                               'provenance_witness_pair_id':pair.pair_id}
            compiled=stages.call('compilation',compilation_input,schema.compilation_schema(labels,pair,current_generation),
                                 lambda v:_compile_validation(v,labels))
            compilations.append({'pair_id':pair.pair_id,'response':compiled})
            if not compiled or not compiled['criteria']:
                continue
            proposed.extend(compiled['criteria'])
            predicted=compiled['predicted_levels']; raw=compiled['criteria'][0]
            signature=canonical_sha256({k:raw[k] for k in ['title','requirement','levels']})
            reason=None
            if labels.index(predicted['preferred']) >= labels.index(predicted['rejected']):
                reason='predicted_relation_not_strict'
            elif raw['provenance_pair_ids'] != [pair.pair_id]:
                reason='provenance_witness_mismatch'
            elif set(raw['replaces']) != set(value['replaces']):
                reason='diagnosis_replacement_mismatch'
            elif occupied.intersection(raw['replaces']):
                reason='overlapping_replacement_set'
            elif signature in duplicate:
                reason='duplicate_proposal'
            if reason:
                failures.append({'stage':'compilation','pair_id':pair.pair_id,'reason':reason});continue
            try:
                candidate=protocol.validated_induction_response(canonical_json({'criteria':[raw]}),
                     original_rubric=original_rubric,current_generation=current_generation,generation_round=generation_round,
                     level_labels=labels,induction_gaps=(pair,))[0]
            except ValueError as exc:
                failures.append({'stage':'compilation','pair_id':pair.pair_id,'reason':'criterion_structure_failure','error':str(exc)});continue
            occupied.update(candidate.replaces);duplicate.add(signature);candidates.append(candidate)
        eligible=[]; validations=[]; reviews=[]
        required_ids=assessment.validation_artifact_ids(comparisons)
        for candidate in candidates:
            criterion=candidate.criterion
            semantic=stages.call('semantic',semantic_input(instruction,original_rubric,current_generation,candidate),schema.semantic_schema())
            applications=list(pool.map(lambda i:stages.call('application',application_input(instruction,artifacts[i],criterion),
                                 schema.application_schema(i,labels)),required_ids))
            native=[]; application_records=[]; blocked=[]
            for identity,value in zip(required_ids,applications,strict=True):
                resolved,errors=([],[]) if value is None else schema.bind_quotes(value['public_evidence'],{identity:public[identity]})
                reason=None
                if value is None:reason='application_unavailable'
                elif errors:reason='application_source_failure'
                elif value['applicability']=='undecidable':reason='application_undecidable'
                elif value['level'] is None:reason='application_missing_level'
                elif value['applicability']=='not_applicable' and value['level']!=labels[0]:reason='not_applicable_non_A'
                elif value['applicability']=='applicable' and not resolved:reason='application_missing_public_evidence'
                if reason:blocked.append({'artifact_id':identity,'reason':reason,'errors':errors})
                else:native.append(protocol.ArtifactApplication(identity,value['level'],value['reason']))
                application_records.append({'artifact_id':identity,'response':value,'resolved_evidence':resolved,'source_errors':errors})
            if semantic is None:blocked.append({'reason':'semantic_unavailable'})
            reviews.append({'criterion_id':criterion.criterion_id,'semantic':semantic,'applications':application_records,'ineligibility':blocked})
            if blocked:
                failures.append({'stage':'validation','criterion_id':criterion.criterion_id,'reason':'candidate_ineligible','details':blocked})
                continue
            eligible.append(candidate)
            validations.append(protocol.CandidateValidation(criterion.criterion_id,semantic['observable'],semantic['nonredundant'],tuple(native),semantic['reason']))
    accepted,admissions=protocol.admit_candidates(tuple(eligible),tuple(validations),comparisons,current_generation)
    active=protocol.update_criteria(current_generation,accepted)
    logical_ceiling=len(history.pairs)+2*len(ids)+3*len(selected)+len(selected)*len(ids)
    budget=logical_ceiling*maximum_stage_attempts(proposer.max_retries)
    if len(stages.records)>logical_ceiling or sum(x['actual_calls'] for x in stages.records)>budget:
        raise RuntimeError('trace learning exceeded its declared logical/attempt budget')
    generation=RubricGeneration(generation_round,source_checkpoint,render_augmented_rubric(original_rubric,active),active,budget,
                               source_schedule=SOURCE_SCHEDULE,red_team_trace_version=VERSION)
    generation.validate_successor(current_generation)
    context={'red_team_trace_version':VERSION,'source_schedule':SOURCE_SCHEDULE,
             'generation_round':generation_round,'source_checkpoint':source_checkpoint,
             'instruction_sha256':sha256_text(instruction),'prior_generation_sha256':current_generation.generation_sha256,
             'original_rubric_sha256':original_rubric.content_sha256,'development_rubric_sha256':development_rubric.content_sha256,
             'artifact_history_sha256':canonical_sha256(history.artifact_record()),
             'proposer':proposer.proposer_contract.record(),'prompt_hashes':prompt_hashes(),
             'implementation_sha256':rubric_generation_implementation_sha256(VERSION)}
    files={
        'artifact-history.json':{'kind':'rubric-induction-evidence',**history.artifact_record()},
        'pairwise-assessment-rubric-free.json':{'red_team_trace_version':VERSION,'pairs':quality_records},
        'pairwise-assessment-active-rubric.json':{'red_team_trace_version':VERSION,'artifacts':view_records[0]},
        'pairwise-assessment-development-rubric.json':{'red_team_trace_version':VERSION,'artifacts':view_records[1]},
        'pairwise-comparisons.json':assessment.comparison_record(comparisons,induction,validation),
        'criterion-proposal.json':{'criteria':proposed,'selection':[p.pair_id for p in selected],
                                   'diagnoses':diagnostics,'compilations':compilations},
        'criterion-validation.json':{'reviews':reviews,'native_validations':[asdict(v) for v in validations], 'ineligibility':failures},
        'aggregate-margins.json':protocol.admission_record(admissions)}
    texts={name:canonical_json(value)+'\n' for name,value in files.items()}
    metadata={'kind':VERSION,'context':context,'generation_sha256':generation.generation_sha256,
              'prior_generation_sha256':current_generation.generation_sha256,
              'accepted_candidate_ids':[c.criterion.criterion_id for c in accepted],
              'rubric_free_preference_count':len(comparisons),'rubric_gap_count':sum(bool(p.gap_views) for p in comparisons),
              'induction_pair_count':len(induction),'validation_pair_count':len(validation),'selected_pair_count':len(selected),
              'logical_call_ceiling':logical_ceiling,'proposer_call_budget':budget,
              'logical_requests':len(stages.records),'actual_calls':sum(x['actual_calls'] for x in stages.records),
              'cache_hits':sum(x['cache_hit'] for x in stages.records),
              'requests':sorted(stages.records,key=lambda x:(x['stage'],x['request_sha256'])),
              'scoring_feasibility':validate_generation_scoring_structure(generation,benchmark=proposer.benchmark)}
    if completed:
        if loaded!=generation:
            raise RuntimeError('replayed trace generation changed')
        stored=load_json_object((root/'evolution.json').read_text(),'trace evolution')
        if stored['context']!=context or stored['generation_sha256']!=generation.generation_sha256:
            raise RuntimeError('trace generation producer context changed')
        for name,text in texts.items():
            if (root/name).read_text()!=text:
                raise RuntimeError('trace generation replay changed '+name)
        return loaded
    texts['evolution.json']=canonical_json(metadata)+'\n'
    persist_rubric_generation(output_dir,generation,policy,evolution_files=texts)
    return generation
