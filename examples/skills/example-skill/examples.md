# Examples — Docker Compose Security Review

## Example 1: Privileged container

### Input

```yaml
services:
  api:
    image: example/api:latest
    privileged: true
    ports:
      - "80:80"
```

### Expected output

```
## Summary
1 critical issue, 2 warnings.

## Critical Issues
- Service `api` runs with `privileged: true`. Remove unless explicitly required,
  and document the requirement in the deployment notes.

## Warnings
- Image uses the `:latest` tag; pin to a specific version for reproducibility.
- Port 80 is exposed publicly without a documented authentication layer.

## Recommended Changes
- Drop `privileged: true`; grant only the specific capabilities needed.
- Pin the image tag (e.g. `example/api:1.4.2`).
- Add a reverse proxy with authentication in front of the API.
```

## Example 2: Docker socket mount

### Input

```yaml
services:
  agent:
    image: example/agent:1.0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

### Expected output

```
## Critical Issues
- Service `agent` mounts the Docker socket directly. This grants root-equivalent
  access to the host. Use a socket proxy (e.g. tecnativa/docker-socket-proxy) or
  a rootless alternative, and restrict the proxied API surface.
```
