# 1. Python, with a lean v1 stack
**Decision:** Python 3.11+, pydantic for schemas. Postgres, Redis, TimescaleDB, FastAPI and Docker are added only when a feature needs them (not for v1, which is a cron job plus SMS).
**Why:** later tax-lot work (HIFO, loss harvesting) benefits from numpy/scipy; the Node prototype's engine is small enough to port with its tests as the spec.
**Revisit:** if the project stays a personal tool, plain scripts plus sqlite are enough.
