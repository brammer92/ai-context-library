PYTHON ?= python3

.PHONY: test validate scan status

test:
	$(PYTHON) -m unittest discover tests

validate:
	$(PYTHON) scripts/validate_memory.py examples/memories/example-memory.md
	$(PYTHON) scripts/validate_skill.py examples/skills/example-skill/SKILL.md

scan:
	$(PYTHON) scripts/scan_secrets.py .

status:
	$(PYTHON) scripts/library_status.py .
