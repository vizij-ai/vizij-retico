# Paper build. `make` produces main.pdf; `make figures` re-exports the d2 sources.
#
# Questrial is the brand-approved free font (see docs/figures/README.md). Point
# QUESTRIAL at it, or `make figures` falls back to d2's default font.

FIGS := 00_idea 01_architecture 02_mapping 03_visemes 04_pipeline
SRC  := ../docs/figures
OUT  := figures
QUESTRIAL ?= $(firstword $(wildcard \
  $(HOME)/Library/Application\ Support/Claude/local-agent-mode-sessions/skills-plugin/*/*/skills/semio-diagrams/brand/fonts/Questrial-Regular.ttf))
FONTFLAG := $(if $(QUESTRIAL),--font-regular "$(QUESTRIAL)",)

.PHONY: all figures clean watch

all: main.pdf

main.pdf: main.tex refs.bib $(addprefix $(OUT)/,$(addsuffix .pdf,$(FIGS)))
	latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex

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
