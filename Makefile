.DEFAULT_GOAL := help

SUITE ?= all
DOCKER ?= 0
XML ?= 0
PYTHON ?= uv run --isolated --project repo/prism-hdl python
BUILD_PYTHON ?= uv run --isolated python
IMAGE ?= prism-hdl:dev
JOBS ?= 4
DOCS_PORT ?= 18743
EXP ?=
ARGS ?= all
EXPERIMENT_PYTHON ?= uv run --python 3.13
EXPERIMENT_IMAGE ?= prism-experiments:dev

RUNNER := repo/prism-hdl/verification/run.py
U280_CLI := repo/prism-hdl/integrations/u280/build.py
RS_FEC ?= on
HOST_UID ?= $(shell id -u 2>/dev/null || echo 1000)
HOST_GID ?= $(shell id -g 2>/dev/null || echo 1000)

ifeq ($(XML),1)
XML_RESULTS_ARG := --xml-results
else
XML_RESULTS_ARG :=
endif

ifeq ($(DOCKER),1)
EXPERIMENT_PREPARE := experiments-docker
EXPERIMENT_EXEC := docker run --rm --user $(HOST_UID):$(HOST_GID) \
	-v "$(CURDIR):/work" -w /work \
	-e HOME=/tmp -e UV_CACHE_DIR=/tmp/uv-cache \
	-e UV_PROJECT_ENVIRONMENT=/tmp/experiment-venv \
	$(EXPERIMENT_IMAGE) python
PREPARE := docker
EXEC := docker run --rm --user $(HOST_UID):$(HOST_GID) \
	-v "$(CURDIR):/work" -w /work \
	-e PRISM_BUILD_DIR=/work/build/cache/rtl-simulation \
	$(IMAGE) python
else
EXPERIMENT_EXEC := $(EXPERIMENT_PYTHON)
PREPARE :=
EXEC := $(PYTHON)
endif

.PHONY: help env build lint test docker docs docs-serve experiments experiment experiments-docker u280 clean

help:
	@echo "PRISM commands"
	@echo "  make test [SUITE=name] [DOCKER=1]  Run verification"
	@echo "  make lint [DOCKER=1]               Run static checks"
	@echo "  make build [DOCKER=1]              Elaborate the RTL"
	@echo "  make docs                           Build documentation"
	@echo "  make docs-serve [DOCS_PORT=18743]    Serve documentation locally"
	@echo "  make experiments                    List valid experiment projects"
	@echo "  make experiment EXP=directory [DOCKER=1] [ARGS=\"all --seed 7\"]"
	@echo "  make u280 [RS_FEC=on|off]           Build the U280 bitstream (one 100G port)"
	@echo "  make clean [DOCKER=1]               Remove verification output"

experiments-docker:
	@docker info >/dev/null 2>&1 || { echo "ERROR: Docker is unavailable."; exit 2; }
	@docker build --target experiments -t "$(EXPERIMENT_IMAGE)" -f repo/prism-hdl/Dockerfile .

experiments: $(EXPERIMENT_PREPARE)
	@$(EXPERIMENT_EXEC) experiments/run/launch.py list

experiment: $(EXPERIMENT_PREPARE)
	@$(EXPERIMENT_EXEC) experiments/run/launch.py run "$(EXP)" -- $(ARGS)

build: $(PREPARE)
	@$(EXEC) $(RUNNER) --build-only

lint: $(PREPARE)
	@$(EXEC) $(RUNNER) --lint-only

test: $(PREPARE)
	@$(EXEC) $(RUNNER) --suite $(SUITE) $(XML_RESULTS_ARG)

env: $(PREPARE)
	@$(EXEC) $(RUNNER) --environment

docker:
	@docker info >/dev/null 2>&1 || { echo "ERROR: Docker is unavailable."; exit 2; }
	@docker build --build-arg USER_ID=$(HOST_UID) --build-arg GROUP_ID=$(HOST_GID) \
		--target test -t $(IMAGE) -f repo/prism-hdl/Dockerfile .

clean: $(PREPARE)
	@$(EXEC) $(RUNNER) --clean

docs:
	@uvx --with-requirements requirements-docs.txt mkdocs build --strict

docs-serve:
	@uvx --with-requirements requirements-docs.txt mkdocs serve --dev-addr "127.0.0.1:$(DOCS_PORT)"

u280:
	@$(BUILD_PYTHON) $(U280_CLI) --rs-fec $(RS_FEC) --threads $(JOBS)
