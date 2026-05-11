# Validation — Docker Compose Security Review

Run the following checks before treating this skill as production-ready.

- [ ] Run the skill on a known-bad Compose file with `privileged: true` and confirm it surfaces a critical issue.
- [ ] Run the skill on a Compose file mounting `/var/run/docker.sock` and confirm it recommends the socket-proxy alternative.
- [ ] Run the skill on a clean Compose file and confirm it returns only minor warnings (or no findings).
- [ ] Confirm no recommendation prints any token, password, or `.env` value verbatim.
- [ ] Re-run `python scripts/validate_skill.py examples/skills/example-skill/SKILL.md` and confirm exit 0.
- [ ] Re-run `python scripts/scan_secrets.py examples/skills/example-skill/` and confirm 0 findings.
