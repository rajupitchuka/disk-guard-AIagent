# Disk Guard IEEE manuscript build
#
# Targets:
#   make            - full build (pdflatex + bibtex + pdflatex x2)
#   make quick      - single-pass pdflatex (no bibliography refresh)
#   make clean      - remove all auxiliary files
#   make distclean  - clean + remove the PDF
#
# Requirements: pdflatex, bibtex (any TeX Live / MacTeX / MiKTeX install)

PAPER = disk-guard
LATEX = pdflatex -interaction=nonstopmode -halt-on-error
BIBTEX = bibtex

.PHONY: all quick clean distclean check

all: $(PAPER).pdf

$(PAPER).pdf: $(PAPER).tex references.bib figures/*.png
	$(LATEX) $(PAPER)
	$(BIBTEX) $(PAPER)
	$(LATEX) $(PAPER)
	$(LATEX) $(PAPER)
	@echo ""
	@echo "✓ built $(PAPER).pdf"
	@echo "  pages: $$(pdfinfo $(PAPER).pdf 2>/dev/null | awk '/^Pages/ {print $$2}')"
	@echo "  size:  $$(du -h $(PAPER).pdf | cut -f1)"

quick:
	$(LATEX) $(PAPER)

check:
	@echo "Checking required tools..."
	@which $(LATEX) >/dev/null 2>&1 && echo "  ✓ pdflatex" || echo "  ✗ pdflatex (install MacTeX or TeX Live)"
	@which $(BIBTEX) >/dev/null 2>&1 && echo "  ✓ bibtex" || echo "  ✗ bibtex"
	@test -f $(PAPER).tex && echo "  ✓ $(PAPER).tex" || echo "  ✗ $(PAPER).tex"
	@test -f references.bib && echo "  ✓ references.bib" || echo "  ✗ references.bib"
	@test -d figures && echo "  ✓ figures/ directory" || echo "  ✗ figures/ directory"
	@ls figures/*.png >/dev/null 2>&1 && echo "  ✓ figures present" || echo "  ✗ no PNGs in figures/"

clean:
	rm -f $(PAPER).aux $(PAPER).bbl $(PAPER).blg $(PAPER).log $(PAPER).out $(PAPER).toc $(PAPER).fls $(PAPER).fdb_latexmk

distclean: clean
	rm -f $(PAPER).pdf
