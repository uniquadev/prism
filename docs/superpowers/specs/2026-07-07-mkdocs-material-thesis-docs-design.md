# MkDocs Material Thesis Docs Design

## Context

Mini-Sharp is a bachelor thesis repository for hardware primitives for network
computing. The repository currently contains a short `README.md`, license
metadata, and an early `docs/TODO.md` outline. Documentation should become a
polished, browsable thesis site while staying easy to maintain as the technical
work evolves.

## Goals

- Follow the MkDocs getting-started layout: a root `mkdocs.yml`, source pages
  under `docs/`, live preview through `mkdocs serve`, and static output under
  ignored `site/`.
- Use Material for MkDocs for an elegant academic documentation experience.
- Provide a clear bachelor-thesis navigation structure instead of a flat page
  dump.
- Add plugins and Markdown extensions that support thesis-grade writing:
  search, diagrams, math, citations, admonitions, code highlighting, tabs,
  tables, footnotes, and easy repository links.
- Configure localization scaffolding with English as the only active language,
  so future translated pages can be added without changing the site structure.
- Keep setup reproducible through a pinned Python requirements file.

## Non-Goals

- Do not generate non-English translated content yet.
- Do not add an automated LLM translation pipeline in this first setup.
- Do not introduce a PDF publishing workflow until the site content is mature
  enough to justify it.
- Do not restructure source code or verification artifacts outside the docs
  setup.

## Recommended Approach

Use MkDocs with the Material theme, a focused plugin set, and a thesis-oriented
page skeleton. This gives the project a polished documentation site now while
keeping localization and future publication workflows possible.

## Site Structure

The initial site should use these pages:

- `index.md`: thesis overview, project identity, and reading paths.
- `getting-started.md`: local setup, simulation/build entry points, and first
  verification flow scaffolding.
- `architecture/index.md`: high-level hardware/software architecture.
- `architecture/protocol.md`: Mini-Sharp protocol and packet format.
- `architecture/pipeline.md`: pipeline and buffering strategy.
- `rtl-verification/index.md`: RTL and verification environment.
- `rtl-verification/testing.md`: tests, traces, and expected validation flows.
- `results/index.md`: performance results and experiment notes.
- `reference/index.md`: compact reference landing page.
- `reference/register-map.md`: register map starter page.
- `reference/interfaces.md`: module and interface reference starter page.
- `thesis/roadmap.md`: thesis writing roadmap derived from the existing
  `docs/TODO.md`.
- `thesis/bibliography.md`: citation and bibliography guidance.

The structure should remain intentionally lightweight: these pages are starter
pages that make the site navigable without pretending the thesis is already
complete.

## Theme

Material for MkDocs should be configured with:

- A restrained academic color palette.
- Navigation tabs and sections for quick exploration.
- Sticky navigation where supported.
- Search suggestions and highlighting.
- Code copy buttons and annotation support.
- Repository link to `https://github.com/uniquadev/mini-sharp`.

The visual tone should be polished and quiet: suitable for a bachelor thesis,
technical enough for hardware readers, and easy to scan during development.

## Plugins And Extensions

Use a small but useful set:

- `search`: built-in MkDocs search.
- `i18n`: from `mkdocs-static-i18n`, configured for English only.
- `autorefs`: stable cross-page references.
- `bibtex`: bibliography and citation support.
- `minify`: compact generated HTML.

Use Markdown extensions for:

- Admonitions and collapsible details.
- Attribute lists and definition lists.
- Footnotes.
- Tables.
- Task lists.
- Tabbed blocks.
- Mermaid diagrams through `pymdownx.superfences`.
- Math through `pymdownx.arithmatex`.
- Highlighted code blocks and inline code highlighting.

## Localization

Localization should be scaffolded but not expanded:

- Default language: English.
- Active languages: English only.
- Future translations can use localized page variants accepted by
  `mkdocs-static-i18n`.
- A short contributor note should explain that LLM-generated translations must
  be reviewed against the English source before publication.

This keeps the main thesis writing flow simple while preserving an obvious path
to Italian or other languages later.

## Error Handling And Maintenance

- Build the site with `mkdocs build --strict` so broken navigation, missing
  pages, and configuration issues fail early.
- Add `site/` to `.gitignore` so generated artifacts stay out of source
  control.
- Keep starter pages explicit about their purpose without adding noisy
  in-app instructions or marketing copy.
- Prefer editing Markdown content over theme overrides unless a clear thesis
  presentation need appears.

## Verification

Implementation is complete when:

- Dependencies install successfully from the requirements file.
- `mkdocs build --strict` succeeds.
- The documentation tree has no missing navigation targets.
- The i18n plugin runs with English as the only active language.
- The site can be previewed with `mkdocs serve`.

## Open Decisions

- The public `site_url` can remain unset until the deployment target is chosen.
- PDF export and automated LLM translation can be added later as separate,
  focused features.
