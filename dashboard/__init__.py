"""A read-only call dashboard for the voice agent.

It changes nothing in the agent. It reads what the agent already writes (the call journal, the agent log) and keeps its own small
database, so the log being truncated at a restart does not lose the history. See dashboard/README.md.
"""
