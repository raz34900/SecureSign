FROM python:3.11-slim

WORKDIR /srv/securesign
COPY pyproject.toml ./
COPY packages ./packages
COPY backend ./backend
COPY scripts ./scripts
COPY models ./models
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
