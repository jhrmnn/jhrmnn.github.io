BLDDIR = build
OUTDIR = _site

.PRECIOUS: $(BLDDIR)/cv.pdf

default: cv

cv: $(OUTDIR)/index.html $(OUTDIR)/cv.pdf $(OUTDIR)/cv.txt $(OUTDIR)/cv.yaml

$(OUTDIR)/%: $(BLDDIR)/% | $(OUTDIR)
	cp $^ $@

$(OUTDIR)/%: data/% | $(OUTDIR)
	cp $^ $@

$(OUTDIR)/index.html: render.py templates/cv.html.in $(wildcard data/*) templates/styles.css $(wildcard assets/*.svg) | $(OUTDIR)
	./$(wordlist 1,5,$^) $(FLAGS) -o $@

$(OUTDIR)/cv.txt: render.py templates/cv.txt.in $(wildcard data/*) | $(OUTDIR)
	./$^ $(FLAGS) -o $@

$(BLDDIR)/%.pdf $(BLDDIR)/%.bbl: $(BLDDIR)/%.tex FORCE
	latexmk -shell-escape -f -pdfxe -outdir=$(BLDDIR) -interaction=nonstopmode $<

$(BLDDIR)/cv.tex: render.py templates/cv.tex.in $(wildcard data/*) | $(BLDDIR)
	./$^ $(FLAGS) -o $@

$(OUTDIR) $(BLDDIR):
	mkdir -p $@

clean:
	rm -rf $(BLDDIR) $(OUTDIR)

distclean: clean
	rm -f .cache.json

FORCE:

dev:
	printf '%s\n' render.py templates/cv.html.in $(wildcard data/*) templates/styles.css | entr make $(OUTDIR)/index.html & \
	printf '%s\n' render.py templates/cv.txt.in $(wildcard data/*) | entr make $(OUTDIR)/cv.txt & \
	printf '%s\n' render.py templates/cv.tex.in $(wildcard data/*) | entr make $(OUTDIR)/cv.pdf & \
	python3 -m http.server -b 0.0.0.0 -d $(OUTDIR)
