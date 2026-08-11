# Claude instructions — agentic-meeting-assistant

**Before doing anything on this repo, read `.claude/HANDOUT.md`.**

It carries the working context that is expensive to rediscover: environment
facts, verified commands, the top landmines, how to work on this codebase, a
running session log, and the open threads. It is maintained by Claude.

**Maintain it.** After any command that changes state — code edited, migration
run, container started, data mutated, decision taken — append a line to
`§6 Session log` and update `§7 Open threads`. Keep entries to one line:
what changed, where, how it was verified.

Two standing rules from this repo, repeated here because ignoring them has
cost real time:

1. **Verify against the live system, not against notes or docstrings.**
   Several docstrings in this codebase contradict their own code
   (`closing_briefing_orchestrator` is the worst offender). `mdfiles/*.md` has
   drifted. Query the database.

2. **Failures here are silent.** Nearly every subsystem wraps itself in
   `except Exception: logger.warning(...)`, so a feature can be completely dead
   while the system looks healthy. Assert on the outcome, never on the absence
   of an error.

Always `export PYTHONIOENCODING=utf-8` before running Python — the codebase has
em-dashes and emoji in docstrings and log lines, and cp1252 will crash on them.
