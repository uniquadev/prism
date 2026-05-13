.PHONY: help image \
		compile compile-local compile-docker \
		passthrough passthrough-local passthrough-docker \
		test shell clean

IMAGE_NAME ?= mini-sharp-rtl:dev
DOCKER ?= docker

# Docker is the default flow.
# Use USE_DOCKER=0 only when local Verilator/Python dependencies are installed.
USE_DOCKER ?= 1

RTL_DIR := $(abspath .)
REPO_ROOT := $(abspath ..)

CONTAINER_REPO_DIR := /work
CONTAINER_RTL_DIR := /work/rtl

MINISHARP_BUILD_DIR ?= /tmp/mini-sharp-rtl/sim_build
MINISHARP_TRACES_DIR ?= verification/traces

# Avoid Docker credential-helper issues for public base images.
DOCKER_CONFIG_DIR ?= /tmp/mini-sharp-docker-config

HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)
DOCKER_USER := $(HOST_UID):$(HOST_GID)

PYTHON_LOCAL ?= $(shell if command -v uv >/dev/null 2>&1; then echo "uv run python"; else echo "python3"; fi)

SV_SOURCES := \
	src/mini_sharp_pkg.sv \
	src/components/eth_parser.sv \
	src/components/minisharp_parser.sv \
	src/math/uint8_to_fp32.sv \
	src/math/fp32_to_uint8_sat.sv \
	src/math/fp32_adder.sv \
	src/math/fp32_alu.sv \
	src/components/reduction_input_converter.sv \
	src/components/reduction_output_converter.sv \
	src/components/reduction_op_decoder.sv \
	src/components/collective_engine.sv \
	src/top/mini_sharp_switch_core.sv \
	vendor/pcap_parse.sv \
	vendor/pcap_dumper.sv \
	src/tb/tb_mini_sharp_switch_core.sv

VERILATOR_LINT_FLAGS := \
	--lint-only \
	-Wall \
	-sv \
	--timing \
	--top-module tb_mini_sharp_switch_core \
	-Wno-WIDTH \
	-Wno-UNOPTFLAT \
	-Wno-CASEINCOMPLETE \
	-Wno-DECLFILENAME \
	-Wno-UNUSEDPARAM \
	-Wno-UNUSEDSIGNAL \
	-Wno-BLKSEQ \
	-Wno-REALCVT \
	-Wno-UNSIGNED \
	-Wno-VARHIDDEN \
	-Wno-IMPORTSTAR \
	-Wno-WIDTHCONCAT \
	-Wno-TIMESCALEMOD \
	-Wno-EOFNEWLINE

help:
	@echo "Mini-Sharp RTL targets"
	@echo ""
	@echo "Default:"
	@echo "  Docker is enabled by default."
	@echo ""
	@echo "Targets:"
	@echo "  make compile                  Lint RTL using Docker by default."
	@echo "  make passthrough              Generate PCAP, run RTL simulation, validate output PCAP."
	@echo "  make test                     Alias for passthrough."
	@echo "  make shell                    Open a Docker shell."
	@echo "  make clean                    Remove generated artifacts."
	@echo ""
	@echo "Options:"
	@echo "  make passthrough USE_DOCKER=0 Run locally."
	@echo "  make passthrough WAVES=1      Enable waveform tracing."
	@echo ""
	@echo "Artifacts:"
	@echo "  traces:    $(MINISHARP_TRACES_DIR)"
	@echo "  sim_build: $(MINISHARP_BUILD_DIR)"
	@echo ""

image:
	mkdir -p "$(DOCKER_CONFIG_DIR)"
	DOCKER_CONFIG="$(DOCKER_CONFIG_DIR)" $(DOCKER) build --pull=false -t "$(IMAGE_NAME)" .

compile:
ifeq ($(USE_DOCKER),1)
	$(MAKE) compile-docker
else
	$(MAKE) compile-local
endif

compile-local:
	verilator $(VERILATOR_LINT_FLAGS) $(SV_SOURCES)

compile-docker: image
	mkdir -p "$(DOCKER_CONFIG_DIR)"
	DOCKER_CONFIG="$(DOCKER_CONFIG_DIR)" $(DOCKER) run --rm \
		--user "$(DOCKER_USER)" \
		-v "$(REPO_ROOT):$(CONTAINER_REPO_DIR)" \
		-w "$(CONTAINER_RTL_DIR)" \
		"$(IMAGE_NAME)" \
		make compile-local USE_DOCKER=0

passthrough:
ifeq ($(USE_DOCKER),1)
	$(MAKE) passthrough-docker
else
	$(MAKE) passthrough-local
endif

passthrough-local:
	MINISHARP_BUILD_DIR="$(MINISHARP_BUILD_DIR)" \
	MINISHARP_TRACES_DIR="$(MINISHARP_TRACES_DIR)" \
	MINISHARP_USE_SYSTEM_TRAFFIC_GEN="$(MINISHARP_USE_SYSTEM_TRAFFIC_GEN)" \
	$(PYTHON_LOCAL) verification/main.py --test passthrough $(if $(WAVES),--waves,)

passthrough-docker: image
	mkdir -p "$(DOCKER_CONFIG_DIR)"
	DOCKER_CONFIG="$(DOCKER_CONFIG_DIR)" $(DOCKER) run --rm \
		--user "$(DOCKER_USER)" \
		-v "$(REPO_ROOT):$(CONTAINER_REPO_DIR)" \
		-w "$(CONTAINER_RTL_DIR)" \
		"$(IMAGE_NAME)" \
		make passthrough-local \
			USE_DOCKER=0 \
			PYTHON_LOCAL=python3 \
			MINISHARP_USE_SYSTEM_TRAFFIC_GEN=1 \
			MINISHARP_BUILD_DIR=/tmp/mini-sharp-rtl/sim_build \
			MINISHARP_TRACES_DIR=verification/traces

test: passthrough

shell: image
	mkdir -p "$(DOCKER_CONFIG_DIR)"
	DOCKER_CONFIG="$(DOCKER_CONFIG_DIR)" $(DOCKER) run --rm -it \
		--user "$(DOCKER_USER)" \
		-v "$(REPO_ROOT):$(CONTAINER_REPO_DIR)" \
		-w "$(CONTAINER_RTL_DIR)" \
		"$(IMAGE_NAME)" \
		bash

clean:
	rm -rf "$(MINISHARP_BUILD_DIR)" || true
	rm -rf .pytest_cache || true
	rm -rf verification/.pytest_cache || true
	rm -rf verification/tests/__pycache__ || true
	rm -rf verification/tests/*.pyc || true
	rm -rf rtl/verification || true
	rm -rf verification/verification || true
	rm -f results.xml || true
	rm -f dump.vcd dump.fst || true
	@if [ -d "$(MINISHARP_TRACES_DIR)" ]; then \
		chmod -R u+rwX "$(MINISHARP_TRACES_DIR)" 2>/dev/null || true; \
		rm -rf "$(MINISHARP_TRACES_DIR)" 2>/dev/null || true; \
	fi
	@if [ -d "$(MINISHARP_TRACES_DIR)" ]; then \
		echo ""; \
		echo "WARNING: could not remove $(MINISHARP_TRACES_DIR)."; \
		echo "The PCAP files may be locked by Windows/Wireshark."; \
		echo "Close Wireshark, then remove the directory manually."; \
		echo ""; \
	fi
