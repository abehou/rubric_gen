"""Report-only path constants; no provider or revision execution."""
import hashlib
from pathlib import Path
BUNDLE = Path(__file__).resolve().parents[1]
ROOT = BUNDLE.parents[1]
RUN = Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20')
V2 = Path('/data/user_data/aydanh/rubric_gen/runs/result20-prompt-nofallback-v2-20260910')
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
