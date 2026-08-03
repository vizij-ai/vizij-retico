# Paper build. `make` produces main.pdf; `make figures` re-exports the d2 sources.
#
# Questrial is the brand-approved free font (see docs/figures/README.md). Point
# QUESTRIAL at it, or `make figures` falls back to d2's default font.

FIGS := 00_idea 01_architecture 02_mapping 03_visemes 04_pipeline \
        05_primer 06_pipeline_simple 07_timeline
SRC  := ../docs/figures
OUT  := figures
# Vendored, not looked up: the previous lookup lived under
# ~/Library/Application Support/... which no co-author has, and which
# $(firstword $(wildcard ...)) truncated at the space regardless.
QUESTRIAL ?= fonts/Questrial-Regular.ttf
FONTFLAG := $(if $(wildcard $(SRC)/$(QUESTRIAL)),--font-regular $(QUESTRIAL),)

BIBS := references.bib suggested_refs.bib vizij_suggested_refs.bib

# references.bib is being curated by hand and entries are migrating into it from
# suggested_refs.bib. Each migration leaves the key defined twice, and a repeated
# entry is a BibTeX *error*: it stops emitting, the .bbl truncates, and every
# citation reads as undefined with nothing in the LaTeX log to say why. Merging
# de-duplicated (references.bib wins) keeps the build working throughout.
merged_refs.bib: merge_bibs.py $(BIBS)
	python3 merge_bibs.py

.PHONY: all figures clean watch suggestions

all: main.pdf

main.pdf: main.tex $(BIBS) $(addprefix $(OUT)/,$(addsuffix .pdf,$(FIGS)))
	latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex

# Kept out of `all` on purpose: main.tex is edited live, and a syntax error there
# should not stop the overlay from building. `make suggestions` builds this alone.
suggestions: pipeline_suggestions.pdf

pipeline_suggestions.pdf: pipeline_suggestions.tex merged_refs.bib $(addprefix $(OUT)/,$(addsuffix .pdf,$(FIGS)))
	latexmk -pdf -interaction=nonstopmode -halt-on-error pipeline_suggestions.tex

# d2 renders SVG; rsvg-convert turns it into the PDF LaTeX wants. Going straight
# to PDF from d2 loses the brand fonts on this toolchain.
$(OUT)/%.pdf: $(SRC)/%.d2 $(SRC)/_brand.d2
	@mkdir -p $(OUT)
	cd $(SRC) && d2 $(FONTFLAG) $*.d2 /tmp/$*.svg
	rsvg-convert -f pdf /tmp/$*.svg -o $@

figures: $(addprefix $(OUT)/,$(addsuffix .pdf,$(FIGS)))

watch:
	latexmk -pdf -pvc -interaction=nonstopmode main.tex

clean:
	latexmk -C
	rm -f main.bbl main.blg
