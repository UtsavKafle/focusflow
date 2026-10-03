# Decisions log
- Track: Applied AI / Databricks only. (Decision-tree track out of scope; revisit only if user says so.)
- SSE without replay cursors; client refetches snapshot on reconnect.
- Load = HR + EDA only for MVP (IBI/RMSSD later).
- Gold polled ~5 s by backend.
- Default cut line (if behind): Sun 05:00 agent must work on fixtures; Sun 08:00 freeze; anything unfinished becomes "future work" slide.
- Data B (Sat): features are pure pandas first (`databricks/features/`), Spark wrappers next. Load = 0.5 HR z + 0.5 EDA z (clamp z/3). Rest = longest still stretch (stillness>=0.9, HR z<=0.5 or unchecked) in last completed local 22:00-08:00 window; null if overnight coverage < 0.7. ACC scale 1/64 g per unit is UNVERIFIED (see provenance). Warm-up 24 h of valid minutes.
- Data B: databricks/ has no __init__.py on purpose (namespace package) so the Databricks SDK/connector imports keep working.
