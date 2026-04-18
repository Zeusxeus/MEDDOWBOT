---
name: meddowbot-docker
description: >
  Docker operations for MEDDOWBOT. Use when managing containers,
  checking service health, reading logs, or deploying the stack.
  Triggers: "start docker", "check services", "docker logs", "container".
---

# MEDDOWBOT Docker Operations

## Quick Reference
```bash
# Development (Redis + PostgreSQL only)
docker compose -f docker/docker-compose.yml up -d redis postgres

# Full stack
docker compose -f docker/docker-compose.yml up -d

# Status
docker compose -f docker/docker-compose.yml ps

# Logs
docker compose -f docker/docker-compose.yml logs -f [service]

# Scale workers
docker compose -f docker/docker-compose.yml up -d --scale worker=5

# Stop
docker compose -f docker/docker-compose.yml down
```

## Services and Ports
- Redis: localhost:6379
- PostgreSQL: localhost:5432 (not exposed publicly)
- Bot: localhost:8080 (/health, /metrics, /webhook)
- Telegram Bot API: localhost:8081
- Prometheus: localhost:9090

## Environment Variables Required
Copy .env.example to .env and fill:
- BOT__TOKEN (required)
- POSTGRES_PASSWORD (required)
- REDIS__URL (has default)
- DATABASE__URL (has default for dev)

## Health Verification
```bash
# All services healthy?
docker compose -f docker/docker-compose.yml ps
# All should show "healthy" or "running"

# Redis:
docker compose exec redis redis-cli ping  # PONG

# PostgreSQL:
docker compose exec postgres pg_isready -U bot -d mediabot  # accepting connections

# Bot:
curl -s http://localhost:8080/health | python3 -m json.tool
```
