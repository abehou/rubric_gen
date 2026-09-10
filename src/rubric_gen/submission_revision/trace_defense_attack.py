"""Private, source-checked attack narration; never a public quality label."""
import json
from pathlib import Path
from rubric_gen.artifacts.hashing import sha256_text, sha256_file
from rubric_gen.submission_revision.user_simulator_history import _solver_visible_replies
from .trace_defense_prompts import VERSION


def quote_offsets(quote: str, content: str) -> list[int]:
    if not isinstance(quote, str) or not quote:
        return []
    offsets, start = [], 0
    while (index := content.find(quote, start)) >= 0:
        offsets.append(index)
        start = index + 1
    return offsets


def attack_record(trajectory: Path, source: str, output: str,
                  source_workspace: Path, output_workspace: Path) -> dict:
    keys = {"status", "rubric_weakness", "attack_mechanism", "quality_damage",
            "why_rubric_may_miss_it", "source_quote", "attack_quote", "modified_files", "relation_check"}
    narration, errors, offsets = None, [], {}
    messages = _solver_visible_replies(trajectory)
    if messages:
        try:
            narration = json.loads(messages[-1])
            if not isinstance(narration, dict) or set(narration) != keys:
                raise ValueError("final JSON fields do not match attack-record contract")
            if narration['status'] not in {'attack_created', 'no_supported_attack'}:
                raise ValueError('invalid narrated attack status')
            if any(not isinstance(narration[k], str) for k in keys - {'modified_files'}):
                raise ValueError('attack narration has non-text fields')
            if not isinstance(narration['modified_files'], list) or any(not isinstance(x,str) for x in narration['modified_files']):
                raise ValueError('invalid modified_files narration')
        except (ValueError, TypeError) as exc:
            errors.append(str(exc)); narration = None
    else:
        errors.append('final assistant narration unavailable')
    if narration is not None:
        for field, content in [('source_quote', source), ('attack_quote', output)]:
            offsets[field] = quote_offsets(narration[field], content)
            if narration[field] and not offsets[field]:
                errors.append(field + ': literal public quote not found')
    def files(root):
        return {p.relative_to(root).as_posix(): sha256_file(p)
                for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
    before, after = files(source_workspace), files(output_workspace)
    changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    return {'kind': 'trace-attack-record-v1', 'red_team_trace_version': VERSION,
            'narration': narration, 'narration_available': narration is not None,
            'source_public_sha256': sha256_text(source), 'output_public_sha256': sha256_text(output),
            'public_nonidentical': source != output, 'actual_changed_files': changed,
            'source_file_sha256s': before, 'output_file_sha256s': after,
            'quote_offsets': offsets, 'source_validation_errors': errors,
            'quote_membership_is_not_scientific_validation': True}
