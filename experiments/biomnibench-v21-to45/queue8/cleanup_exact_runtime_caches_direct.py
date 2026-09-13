"""Remove only the two exact obsolete caches without metadata rewrites.

The prior cleanup's chmod pass exhausted the NFS quota. Directory ownership is
enough for unlinking entries; this operation never traverses outside the fixed
allowlist and refuses the active environment.
"""
from __future__ import annotations
import json, shutil
from pathlib import Path
ROOT=Path('/data/user_data/aydanh/rubric_gen/cache/environments')
ACTIVE=ROOT/'trace-repair-10381602'
TARGETS=(ROOT/'a5f86d3f89f6256c-be8151e15cce-10380168',ROOT/'a5f86d3f89f6256c-d61735ca9b4a-10380169')
RECEIPT=Path(__file__).resolve().parent/'exact-cache-cleanup-receipt-v2.json'
def main():
 if RECEIPT.exists():raise RuntimeError(f'receipt already exists: {RECEIPT}')
 removed=[];absent=[]
 for target in TARGETS:
  if target==ACTIVE:raise RuntimeError('refusing active runtime environment')
  if not target.exists():absent.append(str(target));continue
  if target.is_symlink() or not target.is_dir():raise RuntimeError(f'refusing non-directory cache target: {target}')
  shutil.rmtree(target)
  if target.exists():raise RuntimeError(f'cache target remains: {target}')
  removed.append(str(target))
 receipt={'removed':removed,'already_absent':absent,'active_preserved':str(ACTIVE),'allowlist':[str(p) for p in TARGETS],'metadata_rewrite':False}
 RECEIPT.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');print(json.dumps(receipt,sort_keys=True),flush=True)
if __name__=='__main__':main()
