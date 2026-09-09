ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=300

WORKDIR /opt/crossllm
COPY requirements.lock pyproject.toml ./
COPY src ./src

# The runtime graph is installed only from the hash-checked lock.  Package
# installation is dependency-free so a clean worker cannot resolve a second
# graph from an unpinned package index.
RUN python -m pip install --require-hashes --no-cache-dir --retries 5 --timeout 300 --requirement requirements.lock \
    && python -m pip install --no-cache-dir --no-deps --no-build-isolation . \
    && groupadd --system --gid 65532 crossllm \
    && useradd --system --uid 65532 --gid 65532 --no-create-home crossllm

USER 65532:65532
ENTRYPOINT ["python"]
