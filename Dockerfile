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

# Ensure common mount points exist and are writable by the non-root user
ENV HOME=/home/${USERNAME}
RUN mkdir -p /config "$HOME/.cache/uv" \
 && chown -R ${USER_UID}:${USER_GID} /config "$HOME"

# Make Git tolerant of bind-mounted workspace ownership
RUN git config --system --add safe.directory /workspaces/*

# Run as the non-root user by default
USER ${USERNAME}

CMD ["sleep", "infinity"]
