# Security Policy

## Sensitive Data

The following must never be committed to this repository or shared publicly:

- `.env` files
- IBKR Flex Token / Query ID
- IBKR CSV exports / statements
- LongBridge access / refresh tokens
- LLM API Keys
- Email SMTP passwords
- `data/config/*.json` (may contain tokens and credentials)
- Elasticsearch data directories

## If You Accidentally Commit a Secret

1. **Immediately revoke / rotate** the exposed credential.
2. **Clean Git history** — do not just delete the file. Use `git filter-branch` or `BFG Repo-Cleaner` to purge the secret from all commits.
3. Force-push the cleaned history and notify all collaborators.

## Reporting a Security Issue

Please report security vulnerabilities through **GitHub Security Advisory** or by opening a private issue. Do not include secrets, tokens, or account data in public issues.

## Deployment Reminders

- Do not publicly expose instances with real account data. Place behind VPN / internal network / reverse proxy authentication at minimum.
- Default Docker Compose configuration is intended for local / personal use only.
- Review `scripts/check_release_safety.sh` output before publishing.
