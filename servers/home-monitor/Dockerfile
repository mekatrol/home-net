# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Optional deps (ignored if requirements.txt missing)
RUN --mount=type=cache,target=/root/.cache/pip sh -c '\
    if [ -f requirements.txt ]; then pip install -r requirements.txt; fi'

# Copy app last for better layer caching
COPY . .

# Drop privileges
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Default script name
CMD ["python", "main.py"]
