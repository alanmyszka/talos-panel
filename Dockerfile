FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY talos_panel ./talos_panel
COPY alembic.ini ./
COPY migrations ./migrations
COPY entrypoint.sh ./entrypoint.sh
RUN pip install --no-cache-dir .
RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
