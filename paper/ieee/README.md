# IEEE Conference Manuscript — Disk Guard AI Agent

This folder contains a complete LaTeX submission packet for the
Disk Guard AI Agent paper, formatted for the IEEE conference template
(`IEEEtran`, `conference` option).

## Contents

```
paper/ieee/
├── disk-guard.tex      Main manuscript (~600 lines, IEEEtran/conference)
├── references.bib      22 references in BibTeX format
├── figures/            All 5 figures (PNGs copied from ../../assets/)
│   ├── architecture.png
│   ├── figure_traditional_flow.png
│   ├── figure_predictive_flow.png
│   ├── figure_timeline_comparison.png
│   └── figure_agent_state_machine.png
├── Makefile            One-command local build
└── README.md           This file
```

## Build options

### Option 1 — Overleaf (easiest, no local install)

1. Go to [overleaf.com](https://www.overleaf.com), sign in (free
   account is sufficient)
2. **New Project → Upload Project → Upload zip**
3. Zip the entire `paper/ieee/` folder and upload
4. Overleaf auto-detects `disk-guard.tex` as the main document; click
   **Recompile**
5. The PDF renders in the right pane. Download with the green
   download button next to "Recompile"

### Option 2 — Local build (MacTeX / TeX Live / MiKTeX required)

```bash
cd paper/ieee
make            # full build with bibliography (pdflatex + bibtex + 2 × pdflatex)
make quick      # single pass, useful when iterating without ref changes
make clean      # remove .aux, .log, etc.
make distclean  # also remove the PDF
make check      # verify tools + files are present
```

If `make` is unavailable, the manual incantation:

```bash
pdflatex disk-guard
bibtex disk-guard
pdflatex disk-guard
pdflatex disk-guard
```

The double `pdflatex` after `bibtex` is required so cross-references
to bibliography entries resolve correctly.

### Option 3 — VS Code with LaTeX Workshop extension

Install the **LaTeX Workshop** extension. Open `disk-guard.tex` in
VS Code, click the green ▷ button in the top-right ("Build LaTeX
project"). Output appears in the same folder.

## Installing LaTeX (one-time, if you don't have it)

- **macOS:** `brew install --cask mactex` (large download, ~4 GB; or
  install BasicTeX for a smaller starter kit and add packages as
  needed: `brew install --cask basictex`)
- **Ubuntu/Debian:** `sudo apt-get install texlive-full`
- **Windows:** Download MiKTeX from <https://miktex.org/>

## Expected output

Approximately a **6–8 page PDF** in IEEE 2-column conference format,
including:
- Title, author block, abstract, index terms
- 10 numbered sections + Acknowledgments + References
- 5 figures (full-width spanning both columns)
- 1 table (segment-wise market estimate)
- 22 IEEE-formatted references with DOIs and URLs

## Submission checklist (before submitting to a venue)

- [ ] Replace placeholder author email/affiliation with your actual
      submission details (some venues require ORCID)
- [ ] Verify the venue's page limit (most IEEE conferences allow
      6–8 pages plus references; some allow 10)
- [ ] Run a final spell-check: `aspell check disk-guard.tex`
- [ ] Check that the AI-disclosure statement aligns with the
      specific venue's policy (IEEE's general policy is in the
      manuscript; some venues have stricter or laxer requirements)
- [ ] Compile cleanly with no `??` references (means bibliography
      didn't run; re-run `make`)
- [ ] Submit the PDF; many venues also want the .tex source

## Suggested target venues

| Venue | Type | Page limit | Fit |
|---|---|---|---|
| **IEEE Software** | Magazine | 6 pages | ⭐⭐⭐ Industry-friendly, working POC papers welcome |
| **IEEE Cloud Computing** | Magazine | 6–8 pages | ⭐⭐⭐ Good fit for AIOps work |
| **IEEE Cloud / IEEE SCC** | Conference | 8 pages | ⭐⭐ Academic-leaning |
| **ICSE-SEIP** (Software Eng. in Practice) | Conference | 10 pages | ⭐⭐⭐ Industry track at top SE venue |
| **SREcon (USENIX)** | Conference | Talk-style | ⭐⭐ Adjacent community; shorter format |
| **IEEE Big Data** | Conference | 10 pages | ⭐⭐ If you broaden ML emphasis |
| **AIOps Workshop** (various venues) | Workshop | 4–8 pages | ⭐⭐⭐ Direct fit if you find one in your timeframe |

For maximum impact with minimum revision: **IEEE Software** or
**ICSE-SEIP** (industry track).

## Re-syncing if the markdown whitepaper changes

The `.tex` file was hand-written from the markdown whitepaper at
`docs/disk-guard-whitepaper.md`. They should be kept manually in
sync. If you make substantive edits to the markdown, the easy path
is to re-render the affected sections in the `.tex` by copy-and-paste
+ markdown→LaTeX manual conversion (mostly: `**bold**` → `\textbf{}`,
backticks → `\texttt{}`, headers → `\section{}` / `\subsection{}`,
`[N]` citations → `\cite{key}`).

For larger structural changes a one-shot conversion via Pandoc is
faster:

```bash
pandoc ../../docs/disk-guard-whitepaper.md \
       -o disk-guard-pandoc.tex --bibliography=references.bib \
       --citeproc
```

The output won't be IEEE-formatted but is a useful starting
checkpoint for the body content.
