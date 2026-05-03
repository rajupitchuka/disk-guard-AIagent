# arXiv Submission Guide — Disk Guard AI Agent

This folder contains everything needed to submit the Disk Guard
whitepaper to arXiv. Submission gives the paper a permanent citable
identifier (e.g., `arXiv:2605.XXXXX`) that other researchers and
practitioners can cite — a core piece of evidence for academic
credibility and (where applicable) immigration submissions like
EB1A.

## What's in this folder

```
paper/arxiv/
├── disk-guard.tex          Main manuscript (same content as ../ieee/, IEEEtran format)
├── references.bib          22 references (same as ../ieee/)
├── figures/                5 PNG figures
└── SUBMISSION_GUIDE.md     This file
```

## Step 1 — Compile the paper to verify it builds

You need to compile the paper at least once to produce a `.bbl` file
(the resolved bibliography). arXiv accepts `.tex + .bib + figures`
and runs the compilation itself, but pre-running the compile catches
errors before submission.

**Easiest path: Overleaf**
1. Go to [overleaf.com](https://www.overleaf.com), sign in
2. **New Project → Upload Project**
3. Zip the contents of `paper/arxiv/` (including the `figures/`
   folder) and upload
4. Overleaf opens the project; click **Recompile**
5. If green: you're good. Download the project as a zip — that zip
   contains the compiled `.bbl` you need
6. Confirm the PDF looks correct (no `??` references, all 5 figures
   render, abstract + sections all present)

**Local path (if you have MacTeX installed):**
```bash
cd paper/arxiv
pdflatex disk-guard
bibtex disk-guard
pdflatex disk-guard
pdflatex disk-guard
ls disk-guard.bbl   # confirm it was created
```

## Step 2 — Create the arXiv submission archive

arXiv expects a flat tarball (`.tar.gz`) or zip with the source files.

```bash
cd paper/arxiv
tar -czf disk-guard-arxiv.tar.gz \
    disk-guard.tex \
    references.bib \
    disk-guard.bbl \
    figures/*.png
ls -lh disk-guard-arxiv.tar.gz   # typically <2 MB
```

**Important:** Do NOT include the compiled PDF, log files, .aux,
.out, etc. arXiv only wants the source.

## Step 3 — Create your arXiv account

1. Go to [arxiv.org/user/register](https://arxiv.org/user/register)
2. Register with your TCS email or personal email (your choice;
   personal allows continued access if you change employer)
3. **Endorsement:** First-time arXiv submitters in some categories
   need an endorsement from an existing arXiv author. For the
   categories we'll target (cs.SE, cs.LG, cs.AI), endorsement is
   typically required.
   - Easiest path: ask any colleague who has previously published
     on arXiv to endorse you. The endorsement code request is sent
     by arXiv.
   - Alternative: if you know any researcher in the AIOps / SRE
     space, reach out (LinkedIn DM works) and request an endorsement.
   - Endorsement is a formality once you find someone — they click
     a link.

## Step 4 — Submit the paper

1. Log in to arXiv
2. Click **Submit a new paper**
3. **License:** Recommend **CC BY 4.0** (permissive — anyone can
   share/use with attribution; favored for industry practitioners)
4. **Primary archive / category:**
   - Primary: **cs.SE** (Software Engineering) — best fit for an
     industry-track POC paper
   - Cross-listings (secondary categories): **cs.LG** (Machine
     Learning), **cs.AI** (Artificial Intelligence)
5. **Title:** Disk Guard AI Agent: A Predictive Multi-AI
   Architecture for Proactive Disk-Failure Prevention in Production
   Server Fleets
6. **Authors:** Naga Raju Pitchuka (TCS)
7. **Abstract:** Paste the text from `ABSTRACT_SUBMISSION_TEXT.md`
   (next file in this folder)
8. **Comments field** (optional but valuable): Paste the text from
   `COMMENTS_FIELD.md`
9. **Upload the tarball** (`disk-guard-arxiv.tar.gz`) at the source
   upload step
10. arXiv runs auto-compile (~30 seconds). If it succeeds, preview
    the PDF.
11. Submit. arXiv puts the paper in moderation; typical turnaround
    is 24 hours weekdays.

## Step 5 — After acceptance

1. Within 24–48 hours you'll receive an email with your **arXiv ID**
   (e.g., `2605.12345` for May 2026 submission #12345)
2. The paper goes live at `https://arxiv.org/abs/<arxiv-id>`
3. **Update your GitHub README** to point to the arXiv URL
4. **Update your LinkedIn profile / posts** to cite the arXiv ID
5. **For EB1A evidence:** print the arXiv landing page as PDF and
   keep it; print any download statistics / access metrics arXiv
   provides
6. Subsequent versions: arXiv allows replacing the paper. Each
   replacement creates a new version (v2, v3) but keeps the same
   arXiv ID.

## Categorization rationale

For an industry-track POC paper that combines ML + LLM agents +
operations:

- **cs.SE** (Software Engineering) is primary because the
  contribution is fundamentally a *system architecture* and
  *engineering pattern*. SE papers value working implementations,
  reproducibility, and industrial relevance — all of which apply.
- **cs.LG** (Machine Learning) as cross-listing because the work
  uses Prophet + XGBoost in a non-trivial integration and the
  reasoning includes structured LLM use.
- **cs.AI** (Artificial Intelligence) as cross-listing because the
  agentic LangGraph + RAG pattern is squarely in AI applications.

Avoid cs.DB (databases) — though we use TimescaleDB, the database
work is not the contribution.

## Tips for the abstract field

arXiv abstracts have a 1920-character limit (about 240–280 words).
The current paper abstract is about 350 words — too long. The text
in `ABSTRACT_SUBMISSION_TEXT.md` is a tightened version that fits.

## Tips for the comments field

The comments field is a single line shown on the abstract page.
Use it to indicate page count, presence of code, related artifacts.
Example:

> *14 pages, 5 figures. Working POC source code:
> https://github.com/rajupitchuka/disk-guard-AIagent*

This is a standard format; reviewers and downstream readers find it
helpful for triage.

## What happens if it gets rejected

arXiv almost never *rejects* papers; the moderation team may
re-categorize or ask for clarification. If they ask for a different
category, accept it — the categorization is a tagging convenience,
not a quality judgment. If they flag the paper as borderline
on-topic, respond with a brief note explaining the contribution.
Genuine rejections are extremely rare for technical papers with
working code.

## After arXiv: the next venues

arXiv is a preprint server, not a peer-reviewed publication. Once
the arXiv version is live, you can also submit the same content to:

- IEEE Software (industry magazine, peer-reviewed)
- IEEE Cloud Computing (industry magazine, peer-reviewed)
- ICSE-SEIP (industry track of the top SE conference)
- AIOps Symposium / SREcon (community talks)

These do not double-publish; arXiv is fine alongside any of them.
Conference / journal papers usually become a "v2" or refined
version of the arXiv preprint.
