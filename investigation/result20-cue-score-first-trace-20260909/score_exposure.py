"""Descriptive score-disclosure screen; does not change outcome metrics."""
import collections
import hashlib
import json
import re
from pathlib import Path

PATTERN=re.compile(r"Current assessment for this requirement:\s*([0-9]+(?:\.[0-9]+)?)", re.I)

def summarize(rows):
    seen=set();groups={};exceptions=[]
    for row in rows:
        key=(row['analysis_condition'],row['assignment_id'])
        if key in seen:continue
        seen.add(key)
        state=Path(row['state_path'])
        assert hashlib.sha256(state.read_bytes()).hexdigest()==row['state_sha256']
        counts=groups.setdefault(key[0],collections.Counter())
        counts['assignments']+=1
        for path in sorted((state.parent/'feedback').glob('*.json')):
            raw=path.read_bytes();feedback=json.loads(raw)
            if 'concerns' not in feedback or 'decision' not in feedback:continue
            if feedback['decision']!='revise':
                counts['non_revision_feedback']+=1;continue
            values=[PATTERN.findall(c['feedback']) for c in feedback['concerns']]
            total=sum(map(len,values));counts['revision_feedback']+=1
            first_only=bool(values and len(values[0])==1 and total==1)
            counts['one_first_concern_marker']+=first_only
            counts['no_marker']+=total==0
            counts['multiple_markers']+=total>1
            counts['single_later_marker']+=total==1 and not first_only
            if not first_only:
                exceptions.append(dict(condition=key[0],assignment_id=key[1],path=str(path),sha256=hashlib.sha256(raw).hexdigest(),values_by_concern=values))
    return dict(conditions={k:dict(v) for k,v in groups.items()},exceptions=exceptions,
                caveat='Marker-based screen, accepting omitted points suffix. Absence is not proof of no score disclosure; values and criterion grounding require inspection. Do not condition primary outcomes on compliance.')
