export BLDDIR = build
OUTDIR = _site

vpath %.in templates
vpath %.css templates
vpath %.yaml data
vpath %.json data
vpath %.png assets

.PRECIOUS: %.pdf $(BLDDIR)/%
.DELETE_ON_ERROR:

cv: $(addprefix $(OUTDIR)/,index.html cv.pdf cv.txt cv.yaml)

$(OUTDIR)/%: % | $(OUTDIR)
	cp $^ $@

$(OUTDIR)/%: $(BLDDIR)/% | $(OUTDIR)
	cp $^ $@

$(BLDDIR)/%.b64: % | $(BLDDIR)
	base64 $^ >$@

$(OUTDIR)/%: render.py %.in $(wildcard data/*) | $(OUTDIR)
	./$(wordlist 1,5,$^) $(FLAGS) -o $@

$(BLDDIR)/%: render.py %.in $(wildcard data/*) | $(BLDDIR)
	./$(wordlist 1,5,$^) $(FLAGS) -o $@

$(OUTDIR)/index.html: styles.css $(wildcard assets/*.svg) $(BLDDIR)/favicon.png.b64

%.pdf: %.tex FORCE
	latexmk -shell-escape -f -pdfxe -outdir=$(dir $@) -interaction=nonstopmode $<

$(OUTDIR) $(BLDDIR):
	mkdir $@

clean:
	rm -rf $(BLDDIR) $(OUTDIR)

distclean: clean
	rm -f .cache.json

FORCE:

dev:
	printf '%s\n' render.py templates/index.html.in $(wildcard data/*) templates/styles.css | entr make $(OUTDIR)/index.html & \
	printf '%s\n' render.py templates/cv.txt.in $(wildcard data/*) | entr make $(OUTDIR)/cv.txt & \
	printf '%s\n' render.py --no-statement templates/cv.tex.in $(wildcard data/*) | entr make $(OUTDIR)/cv.pdf & \
	python3 -m http.server -b 0.0.0.0 -d $(OUTDIR)
