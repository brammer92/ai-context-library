---
id: skill_docker_compose_security_review
name: Docker Compose Security Review
version: 1.0.0
description: Reviews Docker Compose files for security, reliability, and maintainability.
status: active
tags:
  - docker
  - security
  - devops
agent_scope:
  - "*"
risk_level: medium
created_at: "2026-05-11T00:00:00Z"
updated_at: "2026-05-11T00:00:00Z"
---

# Docker Compose Security Review

## Purpose

Review Docker Compose files for security, reliability, and maintainability
issues.

## When To Use

Use this skill when reviewing, creating, or modifying Docker Compose
deployments.

## Inputs Expected

- `docker-compose.yml` or `compose.yml`
- `.env.example` when available
- README or deployment notes when available

## Procedure

1. Check for privileged containers.
2. Check for unsafe Docker socket mounts.
3. Check for hardcoded secrets.
4. Check for missing healthchecks.
5. Check for unnecessary exposed ports.
6. Check for missing restart policies.
7. Check for missing named volumes where persistence is required.
8. Check for missing resource limits where appropriate.
9. Check for network isolation.
10. Recommend safer alternatives.

## Output Format

Return a structured review with:

- Summary
- Critical issues
- Warnings
- Recommended changes
- Suggested patch if appropriate

## Safety Checks

- Do not recommend mounting `/var/run/docker.sock` directly unless explicitly justified.
- Do not expose admin services publicly without authentication.
- Do not commit secrets.
- Prefer least privilege.

## Failure Modes

- Missing Compose file
- Ambiguous service purpose
- Environment variables not documented
- Deployment assumptions unclear
