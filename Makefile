SUITE ?= all
DOCKER ?= 0
XML ?= 0
PYTHON ?= uv run python
IMAGE ?= prism-hdl:dev
RUNNER := repo/prism-hdl/verification/run.py
HOST_UID ?= $(shell id -u 2>/dev/null || echo 1000)
HOST_GID ?= $(shell id -g 2>/dev/null || echo 1000)

ifeq ($(XML),1)
XML_RESULTS_ARG := --xml-results
else
XML_RESULTS_ARG :=
endif

ifeq ($(DOCKER),1)
PREPARE := docker
EXEC := docker run --rm --user $(HOST_UID):$(HOST_GID) \
	-v "$(CURDIR):/work" -w /work \
	-e PRISM_BUILD_DIR=/work/build/prism-hdl \
	$(IMAGE) python
else
PREPARE :=
EXEC := $(PYTHON)
endif

.PHONY: build lint test suite env docker clean

build: $(PREPARE)
	@$(EXEC) $(RUNNER) --build-only

lint: $(PREPARE)
	@$(EXEC) $(RUNNER) --lint-only

test: $(PREPARE)
	@$(EXEC) $(RUNNER) --suite $(SUITE) $(XML_RESULTS_ARG)

suite: test

env: $(PREPARE)
	@$(EXEC) $(RUNNER) --environment

docker:
	@docker info >/dev/null 2>&1 || { echo "ERROR: Docker is unavailable."; exit 2; }
	@docker build --build-arg USER_ID=$(HOST_UID) --build-arg GROUP_ID=$(HOST_GID) \
		--target test -t $(IMAGE) -f repo/prism-hdl/Dockerfile .

clean: $(PREPARE)
	@$(EXEC) $(RUNNER) --clean


doc-build:
	@echo "Building documentation..."
	@uvx --with-requirements requirements-docs.txt mkdocs build --strict
doc-serve:
	@echo "Serving documentation..."
	@uvx --with-requirements requirements-docs.txt mkdocs serve
