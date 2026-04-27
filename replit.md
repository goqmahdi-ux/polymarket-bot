# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Each package manages its own dependencies.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)

## Key Commands

- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `pnpm --filter @workspace/api-server run dev` — run API server locally

See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details.

## Polymarket Trading Bot

A Python bot that connects to the Polymarket CLOB and runs a configurable
trading strategy. Lives at the workspace root (not inside `artifacts/`):

- `main.py` — entrypoint
- `bot/` — config, logger, Polymarket client wrapper, strategy
- `.env.example` — settings template (wallet key, risk caps, strategy thresholds)
- `bot/README.md` — full docs and going-live checklist
- Workflow: **`Polymarket Bot`** (`python main.py`)

Default strategy is the **cheap-YES scanner** (buys YES tokens trading at or
below a configurable threshold on liquid markets). Defaults to dry-run mode —
flip `DRY_RUN=false` to trade real funds. Python 3.11; runtime deps in
`pyproject.toml` (`py-clob-client`, `python-dotenv`, `requests`).
