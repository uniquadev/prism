FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy
ENV LD_LIBRARY_PATH=/usr/local/lib

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    make \
    verilator \
    gtkwave \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip \
    && python -m pip install uv \
    && python -m pip install "cocotb>=1.9,<2.0" "scapy>=2.5.0" "pytest>=8.0.0"

WORKDIR /work

CMD ["bash"]