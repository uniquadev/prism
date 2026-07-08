
export NO_MKDOCS_2_WARNING=1

doc-build:
	@echo "Building documentation..."
	@uvx --with-requirements requirements-docs.txt mkdocs build --strict
doc-serve:
	@echo "Serving documentation..."
	@uvx --with-requirements requirements-docs.txt mkdocs serve
