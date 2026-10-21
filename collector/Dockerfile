FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vmeinsight ./vmeinsight

# uid 1000 so a bind-mounted config owned by a normal host user is readable
RUN useradd --uid 1000 --create-home app && mkdir /probe /targets && chown app /probe /targets
USER app

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s \
  CMD python -c "import os,time,sys; sys.exit(time.time()-os.path.getmtime('/tmp/heartbeat') > 300)"
CMD ["python", "-m", "vmeinsight.main"]
