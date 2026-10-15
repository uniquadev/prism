FROM python:3.13.9-slim-trixie AS rtl-base

ARG DEBIAN_FRONTEND=noninteractive
ARG VERILATOR_VERSION=5.032-1+b2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       ca-certificates \
       git \
       make \
       verilator=${VERILATOR_VERSION} \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir \
      cocotb==2.0.1 \
      coverage==7.10.6 \
      mypy==1.17.1 \
      pytest==8.4.1 \
      ruff==0.12.11 \
      scapy==2.7.0

FROM rtl-base AS experiments

RUN python -m pip install --no-cache-dir uv==0.11.7
WORKDIR /work
ENV UV_CACHE_DIR=/tmp/uv-cache \
    UV_PROJECT_ENVIRONMENT=/tmp/experiment-venv
CMD ["python", "experiments/run/launch.py", "list"]

FROM rtl-base AS analysis

ARG DEBIAN_FRONTEND=noninteractive
# Debian replaces the tshark package with every security update, so a fixed
# version stops being installable. Set TSHARK_VERSION to pin one.
ARG TSHARK_VERSION=

RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections \
    && apt-get update \
    && apt-get install -y --no-install-recommends "tshark${TSHARK_VERSION:+=${TSHARK_VERSION}}" \
    && rm -rf /var/lib/apt/lists/*

FROM analysis AS test

ARG USER_ID=1000
ARG GROUP_ID=1000

RUN if ! getent group "${GROUP_ID}" >/dev/null; then groupadd --gid "${GROUP_ID}" prism; fi \
    && if ! getent passwd "${USER_ID}" >/dev/null; then \
       useradd --uid "${USER_ID}" --gid "${GROUP_ID}" --create-home --shell /bin/bash prism; \
       fi

WORKDIR /work

ENV PYTHONPATH=/work/repo/prism-ccl/src:/work/repo/prism-hdl/verification

USER ${USER_ID}:${GROUP_ID}

CMD ["python", "repo/prism-hdl/verification/run.py", "--suite", "all"]
