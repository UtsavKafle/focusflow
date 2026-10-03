# Decisions log
- Track: Applied AI / Databricks only. (Decision-tree track out of scope; revisit only if user says so.)
- SSE without replay cursors; client refetches snapshot on reconnect.
- Load = HR + EDA only for MVP (IBI/RMSSD later).
- Gold polled ~5 s by backend.
- Default cut line (if behind): Sun 05:00 agent must work on fixtures; Sun 08:00 freeze; anything unfinished becomes "future work" slide.
