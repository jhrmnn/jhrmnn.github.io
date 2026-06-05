export BLDDIR = build
OUTDIR = _site
DERIVED = $(BLDDIR)/derived.json
CTX = $(wildcard data/*)

vpath %.in templates
vpath %.css templates
vpath %.yaml data
vpath %.json data
vpath %.png assets
vpath %.jpeg assets

.PRECIOUS: %.pdf $(BLDDIR)/%
.DELETE_ON_ERROR:

cv: $(addprefix $(OUTDIR)/,index.html cv.pdf cv.txt cv.yaml profile-pic.jpeg)

# Refresh the data by crawling live sources; run on schedule/dispatch.
fetch: | $(BLDDIR)
	./fetch.py $(CTX) -o $(DERIVED)

# Otherwise reuse the most recent data artifact from a previous run.
$(DERIVED): | $(BLDDIR)
	./reuse_data.py -o $@

$(OUTDIR)/%: % | $(OUTDIR)
	cp $^ $@

$(OUTDIR)/%: $(BLDDIR)/% | $(OUTDIR)
	cp $^ $@

$(BLDDIR)/%.b64: % | $(BLDDIR)
	base64 $^ >$@

$(OUTDIR)/%: %.in render.py $(CTX) $(DERIVED) | $(OUTDIR)
	./render.py $< $(CTX) --derived $(DERIVED) $(FLAGS) -o $@

$(BLDDIR)/%: %.in render.py $(CTX) $(DERIVED) | $(BLDDIR)
	./render.py $< $(CTX) --derived $(DERIVED) $(FLAGS) -o $@

$(OUTDIR)/index.html: styles.css $(wildcard assets/*.svg) $(BLDDIR)/favicon.png.b64

%.pdf: %.tex FORCE
	latexmk -shell-escape -f -pdfxe -outdir=$(dir $@) -interaction=nonstopmode $<

$(OUTDIR) $(BLDDIR):
	mkdir -p $@

clean:
	rm -rf $(BLDDIR) $(OUTDIR)

distclean: clean
	rm -f .cache.json

FORCE:

dev:
	printf '%s\n' render.py templates/index.html.in $(wildcard data/*) templates/styles.css | entr make $(OUTDIR)/index.html & \
	printf '%s\n' render.py templates/cv.txt.in $(wildcard data/*) | entr make $(OUTDIR)/cv.txt & \
	printf '%s\n' render.py templates/cv.tex.in $(wildcard data/*) | entr make $(OUTDIR)/cv.pdf & \
	python3 -m http.server -b 0.0.0.0 -d $(OUTDIR)
