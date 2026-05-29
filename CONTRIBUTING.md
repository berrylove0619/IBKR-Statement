# Contributing

## Local Development

```bash
cp .env.example .env
docker compose up -d
```

Visit `http://localhost:8080`. See [README.md](README.md) for full details.

## Running Verification

```bash
# Docker full-chain verification
scripts/verify_docker.sh

# Release safety scan
scripts/check_release_safety.sh
```

## Running Tests

```bash
# Backend
pytest ibkr_show_backend/tests

# Worker
pytest ibkr_show_worker/tests

# Frontend
cd ibkr_show_frontend
npm run test
npm run build
```

## Rules

- **Do not commit** real account data, tokens, API keys, or `.env` files.
- New features must include tests.
- Do not mix unrelated refactors into functional commits.
- Sensitive fields in API responses must be masked.
- LongBridge is for public market data only — do not use trading / account / order APIs.
