import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# One process: the per-number locks and the background reply threads live in memory,
# so a second worker process would not see the first one's locks. Scale with threads.
workers = 1
threads = int(os.environ.get("GUNICORN_THREADS", "8"))
worker_class = "gthread"
timeout = 30
accesslog = "-"
