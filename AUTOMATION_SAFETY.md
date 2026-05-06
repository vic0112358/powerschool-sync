# Automation Safety Rules

This project may run on a UVA-monitored computer. Any school email sync,
calendar sync, public report deploy, or recurring automation work must follow
these rules.

- No OS-level persistence.
- No background retry.
- No scratch, cache, or runtime state outside this project directory.
- No copied secrets.
- No copied deploy tokens.
- No deploy queue.
- No deploy unless explicitly configured in the command or automation
  definition and logged.

Operational defaults:

- Local sync may render private and sanitized public HTML.
- Calendar writes must be explicit in the foreground sync path and logged.
- Public publishing must be a foreground command, such as
  `./run_school_sync.sh --deploy-gh-pages`, or an explicitly configured
  automation step that is recorded in `school_sync_runs.log`.
- Deploy scripts must keep all scratch state inside this project directory and
  must not install persistence, watchers, cron jobs, login hooks, or background
  agents.
- Every run must append an auditable line to `school_sync_runs.log`.
