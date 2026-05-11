---
id: mem_20260511_docker_security_preference
title: Docker Security Preference
type: security_note
scope: global
agent_scope:
  - "*"
tags:
  - docker
  - security
importance: high
created_at: "2026-05-11T00:00:00Z"
updated_at: "2026-05-11T00:00:00Z"
source: claude-code
---

# Docker Security Preference

The user prefers Docker Compose-first self-hosted deployments with strong
security defaults.

Agents should avoid mounting `/var/run/docker.sock` directly unless
explicitly approved. Prefer rootless or socket-proxy alternatives when a
container needs Docker API access.
