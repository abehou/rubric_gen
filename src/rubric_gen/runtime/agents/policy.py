"""Shared execution policy and retry constants."""

NO_WEB_POLICY = """
[[rule]]
toolName = "google_web_search"
decision = "deny"
priority = 999
denyMessage = "Web search is disabled for this benchmark run. Use local task data."

[[rule]]
toolName = "web_fetch"
decision = "deny"
priority = 999
denyMessage = "Web fetch is disabled for this benchmark run. Use local task data."
""".lstrip()

MAX_TRANSIENT_RETRIES = 5
