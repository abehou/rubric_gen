"""Host-computed public changes with untrusted private narration, outside scored files."""
import difflib
import json
from pathlib import Path
from rubric_gen.artifacts.hashing import sha256_text, sha256_file
from .user_simulator_history import _solver_visible_replies
from .trace_defense_evidence_v2 import PublicDocument


def attack_record(trajectory, source, output, source_workspace, output_workspace, *, version):
    keys = {'status', 'rubric_weakness', 'attack_mechanism', 'quality_damage',
            'why_rubric_may_miss_it', 'source_sections', 'edited_sections', 'modified_files', 'relation_check'}
    list_fields = {'source_sections', 'edited_sections', 'modified_files'}
    replies = _solver_visible_replies(trajectory)
    raw = replies[-1] if replies else None
    narration, errors = None, []
    try:
        narration = json.loads(raw) if raw is not None else None
        if not isinstance(narration, dict) or set(narration) != keys:
            raise ValueError('final JSON fields do not match attack-record-v2 contract')
        if narration['status'] not in {'attack_created', 'no_supported_attack'}:
            raise ValueError('invalid narrated status')
        if any(not isinstance(narration[k], str) for k in keys-list_fields):
            raise ValueError('non-text narration field')
        if any(not isinstance(narration[k], list) or any(not isinstance(x, str) for x in narration[k]) for k in list_fields):
            raise ValueError('invalid location/file description list')
    except (ValueError, TypeError) as exc:
        errors.append(str(exc)); narration = None
    def files(root):
        return {p.relative_to(root).as_posix(): sha256_file(p) for p in Path(root).rglob('*') if p.is_file() and not p.is_symlink()}
    before, after = files(source_workspace), files(output_workspace)
    a, b = PublicDocument('source', source), PublicDocument('edited', output)
    changes = []
    for tag, i, j, k, l in difflib.SequenceMatcher(None, a.lines, b.lines, autojunk=False).get_opcodes():
        if tag != 'equal':
            changes.append({'operation': tag, 'source': a.resolve(i+1, j) if i<j else None,
                            'edited': b.resolve(k+1, l) if k<l else None,
                            'source_insertion_char_offset': a.char_offsets[i],
                            'edited_insertion_char_offset': b.char_offsets[k]})
    return {'kind': 'trace-attack-record-v2', 'red_team_trace_version': version,
            'raw_final_narration': raw, 'narration': narration, 'narration_available': narration is not None,
            'parse_status': 'available' if narration is not None else 'unavailable', 'parse_errors': errors,
            'source_public_sha256': sha256_text(source), 'output_public_sha256': sha256_text(output),
            'public_nonidentical': source != output,
            'actual_changed_files': sorted(p for p in before.keys()|after.keys() if before.get(p) != after.get(p)),
            'source_file_sha256s': before, 'output_file_sha256s': after, 'public_changes': changes,
            'canonical_public_diff': ''.join(difflib.unified_diff(a.lines, b.lines, fromfile='source_public', tofile='edited_public')),
            'byte_difference_is_not_scientific_validation': True}
