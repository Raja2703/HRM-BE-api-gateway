FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /workspace

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Copy code
COPY . .

# Install dependencies
RUN uv sync --no-dev --no-cache

# Move into service
WORKDIR /workspace

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]