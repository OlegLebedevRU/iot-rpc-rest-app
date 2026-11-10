# Runtime and dependency installer are pinned to reviewed immutable images.
FROM python:3.14.10-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /uvx /bin/
ARG SOURCE_REVISION
ARG SOURCE_ARCHIVE_SHA256
# BuildKit also normalizes image/layer timestamps from this argument. Exposing
# it to RUN makes Python's compiled bytecode use deterministic hash invalidation.
ARG SOURCE_DATE_EPOCH
LABEL org.opencontainers.image.revision=$SOURCE_REVISION \
      io.l4desk.source-archive-sha256=$SOURCE_ARCHIVE_SHA256
# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=tmpfs,target=/tmp uv sync --frozen --no-install-project

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
COPY app-service /app
COPY contracts/l4-media-v3/media.schema.json /contracts/l4-media-v3/
COPY contracts/siplite-camera-v1/camera-rpc.schema.json contracts/siplite-camera-v1/hevc.schema.json contracts/siplite-camera-v1/local-camera.schema.json /contracts/siplite-camera-v1/
COPY contracts/camera-enrollment-proposal/schema.json /contracts/camera-enrollment-proposal/
COPY contracts/camera-ctl-monotonic-v1/camera-ctl.schema.json /contracts/camera-ctl-monotonic-v1/
COPY contracts/camera-enrollment-v0.2/schema.json /contracts/camera-enrollment-v0.2/
COPY contracts/camera-enrollment-v0.3/schema.json /contracts/camera-enrollment-v0.3/
COPY contracts/camera-enrollment-v0.4/schema.json /contracts/camera-enrollment-v0.4/
COPY contracts/camera-enrollment-v0.5/schema.json /contracts/camera-enrollment-v0.5/
COPY contracts/siplite-camera-v1.2/camera.schema.json contracts/siplite-camera-v1.2/manifest.json /contracts/siplite-camera-v1.2/
COPY contracts/siplite-camera-v1.3/camera.schema.json contracts/siplite-camera-v1.3/manifest.json /contracts/siplite-camera-v1.3/
COPY contracts/siplite-camera-v1.4/camera.schema.json contracts/siplite-camera-v1.4/manifest.json /contracts/siplite-camera-v1.4/
COPY contracts/siplite-camera-v1.1/hevc.schema.json /contracts/siplite-camera-v1.1/
# The archive provider resolves this versioned contract outside /app.
# Include only its data files, never the documentation tree or private config.
COPY l4desk-service/docs/prompts/contracts/archive-manifest-v1/archive-manifest.schema.json l4desk-service/docs/prompts/contracts/archive-manifest-v1/examples.json /l4desk-service/docs/prompts/contracts/archive-manifest-v1/
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=tmpfs,target=/tmp uv sync --frozen

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

CMD ["./appup"]
# Run with uvicorn
#CMD ["uv", "run", "uvicorn", "main:main_app", "--host", "0.0.0.0", "--port", "3031"]
#sudo docker run -d --name=app1 --network=net1 -p 127.0.0.1:3031:3031 'test_app'
