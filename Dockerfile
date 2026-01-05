ARG PYTHON_VERSION=3.13-slim
FROM python:${PYTHON_VERSION}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates zsh build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv. I might update this later for more needed packages.
RUN python -m pip install --no-cache-dir -U pip uv && uv --version

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=1000
RUN groupadd --gid ${USER_GID} ${USERNAME} \
 && useradd --uid ${USER_UID} --gid ${USER_GID} -m ${USERNAME} -s /usr/bin/zsh

WORKDIR /workspaces/conductor

CMD ["sleep", "infinity"]
