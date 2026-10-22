FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vmeinsight ./vmeinsight

# unprivileged user the collector runs as (see entrypoint.sh)
RUN useradd --uid 1000 --create-home app && mkdir /probe /targets && chown app /probe /targets
COPY entrypoint.sh /entrypoint.sh

# The entrypoint starts as root only to copy the mounted config (whatever its host owner or mode)
# into a private /config, then drops to uid 1000 with no capabilities before running anything.
ENTRYPOINT ["/entrypoint.sh"]

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s \
  CMD python -c "import os,time,sys; sys.exit(time.time()-os.path.getmtime('/tmp/heartbeat') > 300)"
CMD ["python", "-m", "vmeinsight.main"]
