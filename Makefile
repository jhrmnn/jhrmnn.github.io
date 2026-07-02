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

all: cv notes

cv: $(addprefix $(OUTDIR)/,index.html cv.pdf cv.txt cv.yaml profile-pic-web.jpeg header-blank.png)

POSTS = $(wildcard posts/*.md)

# The notes blog: per-post h-entry permalink pages + an h-feed index, generated
# by posts.py (which writes notes/<YYYY-MM-DD-slug>/index.html as a side
# effect). Rebuilds when any post or shared template/script changes.
notes: $(OUTDIR)/notes/index.html

$(OUTDIR)/notes/index.html: posts.py render.py common.py $(POSTS) \
		templates/post.html.in templates/blog.html.in \
		templates/_head.html templates/_footer.html \
		styles.css $(BLDDIR)/favicon.png.b64 | $(OUTDIR)
	./posts.py posts $(CTX) $(FLAGS) -o $(OUTDIR)

# Refresh the data by crawling live sources; run on schedule/dispatch and on
# pushes/PRs that touch the fetch inputs.
fetch: | $(BLDDIR)
	./fetch.py $(CTX) -o $(DERIVED)

# Verify a freshly fetched dataset hasn't regressed against the last published
# one (run after `make fetch`).
check:
	./check_derived.py $(DERIVED)

# Cross-check that Zotero, ORCID and Google Scholar agree on the publication
# list and its substance (run after `make fetch`, gated to pushes to main).
check-sources:
	./check_sources.py $(DERIVED)

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

$(OUTDIR)/index.html: styles.css $(wildcard assets/*.svg) $(BLDDIR)/favicon.png.b64 \
	templates/_head.html templates/_footer.html assets/superscript.csl

%.pdf: %.tex FORCE
	latexmk -shell-escape -f -pdfxe -outdir=$(dir $@) -interaction=nonstopmode $<

$(OUTDIR) $(BLDDIR):
	mkdir -p $@

# Regenerate the committed homepage avatar from the full-resolution source.
# The homepage only needs a small thumbnail (displayed at 160px, 2x for retina),
# whereas assets/profile-pic.jpeg stays large for the CV PDF (embedded at print
# size). The result is committed and copied by the normal build, so CI needs no
# image tooling; run this by hand (needs ImageMagick, e.g. `apt-get install
# imagemagick`) only when the source photo changes.
avatar:
	convert assets/profile-pic.jpeg -auto-orient -strip -resize 320x320 -quality 82 -interlace JPEG assets/profile-pic-web.jpeg

clean:
	rm -rf $(BLDDIR) $(OUTDIR)

distclean: clean
	rm -f .cache.json

FORCE:

dev:
	printf '%s\n' render.py templates/index.html.in templates/_head.html templates/_footer.html $(wildcard data/*) templates/styles.css | entr make $(OUTDIR)/index.html & \
	printf '%s\n' posts.py render.py templates/post.html.in templates/blog.html.in templates/_head.html templates/_footer.html templates/styles.css $(POSTS) | entr make $(OUTDIR)/notes/index.html & \
	printf '%s\n' render.py templates/cv.txt.in $(wildcard data/*) | entr make $(OUTDIR)/cv.txt & \
	printf '%s\n' render.py templates/cv.tex.in $(wildcard data/*) | entr make $(OUTDIR)/cv.pdf & \
	python3 -m http.server -b 0.0.0.0 -d $(OUTDIR)
