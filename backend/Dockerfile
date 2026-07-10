FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Single worker is not a performance shortcut - it's required. APScheduler
# runs in-process (Section 8); a second worker process would run its own
# copy of the scheduler and every agent would double-scan and potentially
# double-enter trades. Scale this app vertically, not via --workers.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
