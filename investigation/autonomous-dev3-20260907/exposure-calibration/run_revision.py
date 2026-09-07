"""Run a new exposure study, importing only validated exact saved judge requests."""
import hashlib
import json
import runpy
import shutil
import sys
import threading
from pathlib import Path
from rubric_gen.submission_revision.judgment_reuse import ExactJudgmentReuseStore

ROOT = Path(__file__).resolve().parents[3]
SOURCES = [
    ROOT/'runs/autonomous-dev3-20260907/isolation-cachefix-smoke/study/biomnibench-da-factorial-r3-3686c8965c2e/shared-judgments/judge',
    ROOT/'runs/autonomous-dev3-20260907/baseline-da11/study/biomnibench-da-factorial-r3-ac929d893d67/shared-judgments/judge',
]
_original = ExactJudgmentReuseStore.resolve
_lock = threading.Lock()

def resolve(self, *, request, producer, generate):
    key = hashlib.sha256(self._canonical_request_text(request).encode()).hexdigest()
    destination = self.entries/key
    with _lock:
        if not destination.exists():
            for root in SOURCES:
                source = root/'entries'/key
                if not source.exists():
                    continue
                ExactJudgmentReuseStore(root)._load(source, request)
                self.entries.mkdir(parents=True, exist_ok=True)
                stage = self.entries/('.import-'+key)
                if stage.exists():
                    raise RuntimeError(f'Interrupted cache import requires inspection: {stage}')
                shutil.copytree(source, stage)
                self._validate_entry(stage, request, require_canonical_name=False)
                stage.rename(destination)
                with (self.root/'imported-requests.jsonl').open('a') as ledger:
                    ledger.write(json.dumps({'key':key,'source':str(source)})+'\n')
                print(f'Imported exact saved judgment {key}', flush=True)
                break
    return _original(self, request=request, producer=producer, generate=generate)

if __name__ == '__main__':
    ExactJudgmentReuseStore.resolve = resolve
    runpy.run_path(str(ROOT/'investigation/autonomous-dev3-20260907/run_workflow.py'), run_name='__main__')
