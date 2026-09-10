"""Print bounded saved-event excerpts, preserving original turn/line locations."""
import argparse
import json
import re
from collect import OUT

p=argparse.ArgumentParser()
p.add_argument('case');p.add_argument('--pattern');p.add_argument('--turn',type=int)
p.add_argument('--line',type=int);p.add_argument('--limit',type=int,default=35)
p.add_argument('--offset',type=int,default=0);p.add_argument('--chars',type=int,default=650)
a=p.parse_args(); hits=[]
for line in (OUT/'traces'/a.case/'events.jsonl').read_text().splitlines():
    e=json.loads(line)
    if e['event']!='item.completed':continue
    if a.turn is not None and e['turn']!=a.turn:continue
    if a.line is not None and e['line']!=a.line:continue
    text=e['text']
    if a.pattern:
        match=re.search(a.pattern,text,re.I)
        if not match:continue
        start=max(0,match.start()-a.chars//3);text=text[start:start+a.chars]
    else:text=text[:a.chars]
    hits.append((e,text))
print('matching events',len(hits))
for e,text in hits[a.offset:a.offset+a.limit]:
    print(f'\nTURN {e["turn"]} LINE {e["line"]} {e["item_type"]} {e["item_id"]}\n{text}')
