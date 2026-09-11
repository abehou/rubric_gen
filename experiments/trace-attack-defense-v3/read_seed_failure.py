from pathlib import Path

paths = [
    Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/control-v21-compatible/inputs/da-3-4/seed/tasks/da-3-4/rep-001/.initial-judge-work/evaluations/submission/42717e7ac08cf231b0d6aa1c79e186b7ba49375ff60b8180cc689095447eef6c/b640d1abd2bfb054d7b7d7030cbefcad/run/judges/trace/da-3-4/stdout.txt'),
    Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/control-v21-compatible/inputs/da-18-1/seed/tasks/da-18-1/rep-001/.initial-judge-work/evaluations/submission/7d773f04c056fb4da68dc706f0ce78c2f9cc30b9d08a023d3f2b182e87d53698/8a7ff5468eb50adfbec527656d9010f3/run/judges/trace/da-18-1/stdout.txt'),
]
for path in paths:
    print('PATH', path, 'exists', path.is_file())
    if path.is_file():
        print(path.read_text(errors='replace')[-6000:])
