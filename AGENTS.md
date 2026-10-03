# Instructions for coding agents (Claude Code, Cursor, Codex, etc.)
1. Read `docs/handoffs/00-common.md` first, then the handoff for YOUR role (`01-data-a.md`, `02-data-b.md`, `03-integrator.md`, `04-frontend.md`). Ask your human which role they are if unclear.
2. Only edit files in the directories your role owns. Never edit `contracts/models.py` or `contracts/schema/*`; request changes from the Integrator.
3. Full product spec: `docs/HANDOFF.md`. Contracts: `contracts/`. Run `pytest -q` before every push.
4. Never commit secrets or raw participant data. Never present synthetic data as real wearable data.
