# Security Policy

## Reporting a vulnerability

If you discover a security issue in NullVector, **do not open a public GitHub issue**.
Email the maintainer directly at `pruthvi2799@gmail.com` with:

- A description of the issue
- Steps to reproduce (if applicable)
- The commit SHA or release tag where you observed it

You will get an acknowledgment within 72 hours.

## Secret handling — non-negotiable rules

NullVector talks to LLM providers and databases, so credentials are part of the
operating surface. The rules below exist because they were broken once and
required a full git-history rewrite to clean up. Read them.

### Never commit secrets

- All API keys, tokens, passwords, and DSNs **must** come from environment
  variables, never from source files, notebooks, or markdown.
- The canonical template is [`.env.example`](./.env.example). It lists every
  variable the codebase reads. Copy it to `.env` (which is gitignored) and fill
  in real values locally.
- Cookbook notebooks and tests must read from `os.environ` / `os.getenv`.
  Hardcoding a key for "just a quick test" is the failure mode that caused
  the prior incident.

### Forbidden patterns in commits

The following patterns will fail the pre-commit hook and the `secret-scan`
GitHub Action. Do not try to bypass them — fix the leak.

| Pattern | Provider |
|---------|----------|
| `gsk_[A-Za-z0-9]{52}` | Groq |
| `sk-or-v1-[A-Za-z0-9]{64}` | OpenRouter |
| `sk-ant-api03-...` | Anthropic |
| `sk-proj-...` / `sk-svcacct-...` | OpenAI |
| `AKIA[0-9A-Z]{16}` | AWS access key |
| `ghp_...` / `github_pat_...` | GitHub PAT |
| `postgresql://user:pass@...` with non-placeholder credentials | Postgres DSN |

### What `pre-commit` does

The repo ships a `.pre-commit-config.yaml` with:

- **`gitleaks`** — scans staged content against the regexes above
- **`detect-private-key`** — blocks RSA/EC/ED25519 private key blobs
- **`check-added-large-files`** — refuses files >1 MB (caught the 531KB
  `CHANGE_DIFF.md` artifact that contributed to the prior leak)

Install once after cloning:

```bash
uv tool install pre-commit  # or: pipx install pre-commit
pre-commit install
```

Every `git commit` from then on runs the scan.

### What CI does

`.github/workflows/secret-scan.yml` runs `gitleaks-action@v2` on every push and
pull request, against the full history (`fetch-depth: 0`). A new leak fails the
workflow even if it slipped past pre-commit.

### What GitHub does

The repo also has GitHub-side **Secret Scanning** and **Push Protection**
enabled (Settings → Code security and analysis). These block known-secret
patterns at `git push` time, server-side, on top of the local + CI scans.

## Rotation runbook

If a secret leaks (in code, log output, error message, screenshot, etc.),
**rotate first, scrub second**. The leaked value is exploitable from the
moment it touched a public surface — anyone with a clone retains it forever.

| Provider | Console URL | Action |
|----------|-------------|--------|
| Groq | https://console.groq.com/keys | Revoke the leaked key, create a fresh one, store in your local `.env` |
| OpenRouter | https://openrouter.ai/settings/keys | Revoke the leaked key, create a fresh one |
| OpenAI | https://platform.openai.com/api-keys | Revoke and reissue |
| Anthropic | https://console.anthropic.com/settings/keys | Revoke and reissue |
| Postgres (local) | `psql` → `ALTER USER ... WITH PASSWORD ...` | Change the password; update `.env` |

After rotation, run a history-rewrite cleanup using `git-filter-repo`. See
the previous incident plan at
`~/.claude/plans/inherited-kindling-reddy.md` for the full procedure.

## Defense-in-depth checklist

If you're touching anything that handles credentials, confirm:

- [ ] No literal key in source / notebooks / markdown / fixtures
- [ ] `.env.example` updated with any new variable name
- [ ] `pre-commit run --all-files` passes locally
- [ ] No log statement prints `Authorization`, `Bearer`, `api_key`, or DSN values
- [ ] Test fixtures use placeholder values (`test-key-...`) that won't false-positive on scanners
- [ ] Anything secret-adjacent in a notebook output cell is cleared before commit
