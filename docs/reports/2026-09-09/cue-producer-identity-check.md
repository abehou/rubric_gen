# Verified producer/consumer identity boundary

The genuine frozen cue producer loader reconstructs `biomnibench-da-factorial-r10-f0203f5d69f3` from the unchanged source YAML. Its prompt implementation digest is `e3f0c1ad59899ab81252d03aef3984e93c69c535a1f3f0aa066078e97e53e788`.

The candidate loader reconstructs `biomnibench-da-factorial-r10-674329626c7c` from that same YAML because its prompt implementation digest is `3b108c07ba41bf1fbd81c64d98cc37610236cd934decf3223989ee3edf947c2e`. No task, source YAML or historical metadata change is needed to explain validation10373088's failure.

The source is not obsolete or corrupt: its own frozen current-format loader accepts it. The defective boundary is applying consumer implementation identity when checking an explicitly declared producer input. New-study identity must continue binding the candidate prompt implementation.

Required correction: validate the declared producer using a separately pinned producer receipt/source identity, then compare reusable input contracts and native rubric histories under the consumer. The receipt must bind the original YAML, original prompt digest, completed study identity and input file hashes. Require evidence from the frozen producer; reject wrong YAML, wrong producer identity, unfinished source, mismatched input contracts and changed files. Do not accept an unchecked digest supplied merely to make an ID match; do not alter historical receipts, monkeypatch global identity hashing, or remove prompt hashing from new experiments.

The adjacent JSON records the verified producer loader output. It is diagnostic evidence, not yet an accepted runtime import receipt. Scientific launch remains gated on implementing and testing this boundary.
