
.PHONY: help image \
		compile compile-local compile-docker \
		tests tests-local tests-docker \
		test passthrough passthrough-local passthrough-docker \
		run_pcap run_pcap-local run_pcap-docker \
		shell clean

IMAGE_NAME ?= mini-sharp-rtl:dev
DOCKER ?= docker

# Docker is the default flow.
# Use USE_DOCKER=0 only when local Verilator/Python dependencies are installed.
USE_DOCKER ?= 1

RTL_DIR := $(shell pwd -P)
REPO_ROOT := $(abspath $(RTL_DIR)/..)

CONTAINER_REPO_DIR := /work
CONTAINER_RTL_DIR := /work/rtl

MINISHARP_BUILD_DIR ?= /tmp/mini-sharp-rtl/sim_build
MINISHARP_TRACES_DIR ?= verification/traces

DOCKER_CONFIG_DIR ?= /tmp/mini-sharp-docker-config

HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)
DOCKER_USER := $(HOST_UID):$(HOST_GID)

PYTHON_LOCAL ?= $(shell if command -v uv >/dev/null 2>&1; then echo "uv run python"; else echo "python3"; fi)

# Custom PCAP runner.
#
# Supported syntax:
#   make run_pcap input.pcap
#   make run_pcap input.pcap output.pcap
#   make run_pcap PCAP_IN=input.pcap
#   make run_pcap PCAP_IN=input.pcap PCAP_OUT=output.pcap
PCAP_OUT ?= $(abspath out.pcap)

RUN_PCAP_POSITIONAL_ARGS := $(filter-out run_pcap,$(MAKECMDGOALS))

ifeq ($(firstword $(MAKECMDGOALS)),run_pcap)
ifneq ($(RUN_PCAP_POSITIONAL_ARGS),)
PCAP_IN ?= $(word 1,$(RUN_PCAP_POSITIONAL_ARGS))
ifneq ($(word 2,$(RUN_PCAP_POSITIONAL_ARGS)),)
PCAP_OUT := $(word 2,$(RUN_PCAP_POSITIONAL_ARGS))
endif
endif
.PHONY: $(RUN_PCAP_POSITIONAL_ARGS)
endif

PCAP_IN_ABS := $(abspath $(PCAP_IN))
PCAP_OUT_ABS := $(abspath $(PCAP_OUT))

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
	@echo "  make compile                         Lint RTL."
	@echo "  make tests                           Run the full regression suite."
	@echo "                                       Currently: INT8 reduction + FP32 reduction."
	@echo "  make test                            Alias for tests."
	@echo "  make run_pcap <input.pcap>           Run DUT on a custom PCAP without payload validation."
	@echo "  make run_pcap <input.pcap> <out.pcap>"
	@echo "                                       Positional syntax."
	@echo "  make run_pcap PCAP_IN=<path> PCAP_OUT=<path>"
	@echo "                                       Variable syntax."
	@echo "  make shell                           Open a Docker shell."
	@echo "  make clean                           Remove generated artifacts."
	@echo ""
	@echo "Backward-compatible alias:"
	@echo "  make passthrough                     Alias for tests."
	@echo ""
	@echo "Options:"
	@echo "  USE_DOCKER=0                         Run locally."
	@echo "  WAVES=1                              Enable Verilator waveform tracing."
	@echo ""
	@echo "Artifacts:"
	@echo "  traces:    $(MINISHARP_TRACES_DIR)"
	@echo "  sim_build: $(MINISHARP_BUILD_DIR)"
	@echo ""

check-docker-paths:
	@if [ -z "$(REPO_ROOT)" ]; then echo "ERROR: REPO_ROOT is empty."; exit 2; fi
	@if [ ! -d "$(REPO_ROOT)" ]; then echo "ERROR: REPO_ROOT does not exist: $(REPO_ROOT)"; exit 2; fi
	@if [ -z "$(RTL_DIR)" ]; then echo "ERROR: RTL_DIR is empty."; exit 2; fi
	@if [ ! -d "$(RTL_DIR)" ]; then echo "ERROR: RTL_DIR does not exist: $(RTL_DIR)"; exit 2; fi

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

compile-docker: image check-docker-paths
	mkdir -p "$(DOCKER_CONFIG_DIR)"
	DOCKER_CONFIG="$(DOCKER_CONFIG_DIR)" $(DOCKER) run --rm \
		--user "$(DOCKER_USER)" \
		-v "$(REPO_ROOT):$(CONTAINER_REPO_DIR)" \
		-w "$(CONTAINER_RTL_DIR)" \
		"$(IMAGE_NAME)" \
		make compile-local USE_DOCKER=0

tests:
ifeq ($(USE_DOCKER),1)
	$(MAKE) tests-docker
else
	$(MAKE) tests-local
endif

tests-local:
	MINISHARP_BUILD_DIR="$(MINISHARP_BUILD_DIR)" \
	MINISHARP_TRACES_DIR="$(MINISHARP_TRACES_DIR)" \
	MINISHARP_USE_SYSTEM_TRAFFIC_GEN="$(MINISHARP_USE_SYSTEM_TRAFFIC_GEN)" \
	$(PYTHON_LOCAL) verification/main.py --test tests $(if $(WAVES),--waves,)

tests-docker: image check-docker-paths
	mkdir -p "$(DOCKER_CONFIG_DIR)"
	DOCKER_CONFIG="$(DOCKER_CONFIG_DIR)" $(DOCKER) run --rm \
		--user "$(DOCKER_USER)" \
		-v "$(REPO_ROOT):$(CONTAINER_REPO_DIR)" \
		-w "$(CONTAINER_RTL_DIR)" \
		"$(IMAGE_NAME)" \
		make tests-local \
			USE_DOCKER=0 \
			PYTHON_LOCAL=python3 \
			MINISHARP_USE_SYSTEM_TRAFFIC_GEN=1 \
			MINISHARP_BUILD_DIR=/tmp/mini-sharp-rtl/sim_build \
			MINISHARP_TRACES_DIR=verification/traces

# Backward-compatible aliases.
test: tests
passthrough: tests
passthrough-local: tests-local
passthrough-docker: tests-docker

run_pcap:
ifeq ($(strip $(PCAP_IN)),)
	$(error Missing input PCAP. Usage: make run_pcap input.pcap [output.pcap] OR make run_pcap PCAP_IN=/path/input.pcap [PCAP_OUT=/path/output.pcap])
endif
	@if [ ! -f "$(PCAP_IN_ABS)" ]; then \
		echo "Input PCAP not found: $(PCAP_IN_ABS)"; \
		exit 2; \
	fi
ifeq ($(USE_DOCKER),1)
	$(MAKE) run_pcap-docker \
		PCAP_IN="$(PCAP_IN_ABS)" \
		PCAP_OUT="$(PCAP_OUT_ABS)"
else
	$(MAKE) run_pcap-local \
		PCAP_IN="$(PCAP_IN_ABS)" \
		PCAP_OUT="$(PCAP_OUT_ABS)"
endif

run_pcap-local:
	MINISHARP_BUILD_DIR="$(MINISHARP_BUILD_DIR)" \
	MINISHARP_TRACES_DIR="$(MINISHARP_TRACES_DIR)" \
	$(PYTHON_LOCAL) verification/main.py \
		--test run_pcap \
		--input-pcap "$(PCAP_IN)" \
		--output-pcap "$(PCAP_OUT)" \
		$(if $(WAVES),--waves,)

run_pcap-docker: image check-docker-paths
	mkdir -p "$(DOCKER_CONFIG_DIR)"
	mkdir -p "$(dir $(PCAP_OUT))"
	DOCKER_CONFIG="$(DOCKER_CONFIG_DIR)" $(DOCKER) run --rm \
		--user "$(DOCKER_USER)" \
		-v "$(REPO_ROOT):$(CONTAINER_REPO_DIR)" \
		-v "$(dir $(PCAP_IN)):/input:ro" \
		-v "$(dir $(PCAP_OUT)):/output" \
		-w "$(CONTAINER_RTL_DIR)" \
		"$(IMAGE_NAME)" \
		make run_pcap-local \
			USE_DOCKER=0 \
			PYTHON_LOCAL=python3 \
			MINISHARP_BUILD_DIR=/tmp/mini-sharp-rtl/sim_build \
			MINISHARP_TRACES_DIR=verification/traces \
			PCAP_IN="/input/$(notdir $(PCAP_IN))" \
			PCAP_OUT="/output/$(notdir $(PCAP_OUT))"

shell: image check-docker-paths
	mkdir -p "$(DOCKER_CONFIG_DIR)"
	DOCKER_CONFIG="$(DOCKER_CONFIG_DIR)" $(DOCKER) run --rm -it \
		--user "$(DOCKER_USER)" \
		-v "$(REPO_ROOT):$(CONTAINER_REPO_DIR)" \
		-w "$(CONTAINER_RTL_DIR)" \
		"$(IMAGE_NAME)" \
		bash

clean:
	rm -rf "$(MINISHARP_BUILD_DIR)" \
		   "$(MINISHARP_TRACES_DIR)" \
		   .pytest_cache \
		   verification/.pytest_cache \
		   verification/__pycache__ \
		   verification/tests/__pycache__ \
		   verification/tests/*.pyc \
		   rtl/verification \
		   verification/verification \
		   results.xml \
		   dump.vcd \
		   dump.fst \
		   out.pcap || true

# Swallow positional arguments used by:
#   make run_pcap input.pcap [output.pcap]
%:
	@if [ "$(firstword $(MAKECMDGOALS))" = "run_pcap" ]; then \
		:; \
	else \
		echo "Unknown target '$@'"; \
		exit 2; \
	fi
