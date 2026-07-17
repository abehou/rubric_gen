"""Solver prompt and provider policy constants."""

PROMPT = """You are solving one BiomniBench-DA task in the current directory.

Read ./instruction.md and use only the files under ./data as task data.
Do not read the source paper, source-paper figures, or source-paper supplements.
Do not use web search, web fetch, or browser tools unless the runner explicitly
allows them. Prefer local data analysis and installed package documentation.

Produce exactly these local files:
- ./trace.md: the full analysis trace requested by the instruction.
- ./answer.txt: the final plain-text answer requested by the instruction.

Keep trace.md concise: summarize key commands, scripts, data shapes, metrics,
statistical choices, and limitations; do not paste long tables or full script
bodies when those scripts are saved in the workspace. Write a short provisional
answer.txt as soon as you have a viable result, then update it before stopping.

Use a local uv environment for Python analysis work. If you need Python packages,
create it with `uv venv .venv`, install packages with `uv pip install --python
.venv/bin/python ...`, and run analysis scripts with `.venv/bin/python`.

You may write and run small Python or R scripts in this directory. Keep notes
of commands, intermediate counts, statistical choices, and limitations in
trace.md. Before stopping, verify that both trace.md and answer.txt exist and
are non-empty.
"""

NO_WEB_POLICY = """
[[rule]]
toolName = "google_web_search"
decision = "deny"
priority = 999
denyMessage = "Web search is disabled for this BiomniBench run. Use local task data."

[[rule]]
toolName = "web_fetch"
decision = "deny"
priority = 999
denyMessage = "Web fetch is disabled for this BiomniBench run. Use local task data."
""".lstrip()

MAX_TRANSIENT_RETRIES = 5
