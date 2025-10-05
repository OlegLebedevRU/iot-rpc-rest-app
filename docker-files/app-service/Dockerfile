# Use a Python image with uv pre-installed
#FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
# Install uv
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
   # --mount=type=bind,source=uv.lock,target=uv.lock \
  #  --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
COPY app-service /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Reset the entrypoint, don't invoke `uv`
RUN chmod +x prestart.sh
RUN chmod +x appup

ENTRYPOINT ["./prestart.sh"]

# Run the FastAPI application by default
# Uses `fastapi dev` to enable hot-reloading when the `watch` sync occurs
# Uses `--host 0.0.0.0` to allow access from outside the container
#CMD ["fastapi", "dev", "--host", "0.0.0.0", "src/uv_docker_example"]
RUN["./appup"]
# Run with uvicorn
#CMD ["uv", "run", "uvicorn", "main:main_app", "--host", "0.0.0.0", "--port", "3031"]
#sudo docker run -d --name=app1 --network=net1 -p 127.0.0.1:3031:3031 'test_app'