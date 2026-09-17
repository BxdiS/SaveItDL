# Notes for Claude

## Project

SaveItDL — a multi-platform media downloader bot. Core download logic (yt-dlp) is shared; platform adapters (Telegram first, Discord later) plug into it. Python 3.11+, aiogram 3, asyncio worker pool.

## Commits

Conventional Commits for commit subjects:

```
type(scope): description
```

Types: `feat`, `fix`, `docs`, `refactor`, `perf`, `chore`. Imperative mood, lowercase, no trailing period, under 72 characters total.

**Small, confident changes** (typo fix, config tweak, dependency bump, one-liner that obviously doesn't break anything) can go straight to `main` without a branch or PR. If there's any doubt — branch and PR.

Larger changes go through a branch (`feat/`, `fix/`, `docs/`) and a PR. PRs are squash-merged.

## What not to touch without good reason

- `core/downloader.py` format strings for yt-dlp — these are tuned for compatibility across sites; a "cleaner" format selection can silently break specific extractors.
- `MAX_WORKERS` / `QUEUE_SIZE` defaults — chosen to fit a 2 vCPU / 4 GB server. Changing them changes the resource profile.
- The `asyncio.Semaphore` in `worker_pool.py` — it's the concurrency gate. Don't replace it with a different mechanism without benchmarking.

## Specific to you

**Never add tool attribution lines** — no "Generated with Claude Code", no "Co-authored-by: Claude" of any kind, in commits or PR descriptions. Focus on the technical content.

## Tooling

Needs `git` and `gh` on PATH, with `gh` authenticated.

`gh pr create --body "..."` and `git commit -m "..."` break in PowerShell when the text contains double quotes. Write the text to a file and use `--body-file` or `git commit -F`.
