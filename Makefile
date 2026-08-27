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

cv: $(addprefix $(OUTDIR)/,index.html cv.pdf cv-tech.pdf cv-academic.pdf cv-academic.txt cv.yaml profile-pic-web.png)

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
	./fetch.py -o $(DERIVED)

# Verify a freshly fetched dataset hasn't regressed against the last published
# one (run after `make fetch`).
check:
	./check_derived.py $(DERIVED)

# Cross-check that Zotero, ORCID and Google Scholar agree on the publication
# list and its substance (run after `make fetch`, gated to pushes to main).
check-sources:
	./check_sources.py $(DERIVED)

# Report how the two one-pager CVs (cv.pdf, the research variant, and
# cv-tech.pdf, the technical-program-leadership variant) survive the parser
# families an applicant-tracking system might use: the name and contact must
# lead, each job record must come out whole, and the main column's landmarks
# must stay in document order. The two share the layout but tell the career
# differently, so check_cv_parsing.py picks a per-file marker profile by
# filename. Needs the `test` dependency group and poppler-utils; an extractor
# that will not load is itself a failure, so a thin environment cannot report
# green on a subset. Every check is a hard failure -- the script exempts nothing,
# because it no longer asks for perfect column contiguity.
check-cv: $(OUTDIR)/cv.pdf $(OUTDIR)/cv-tech.pdf
	./check_cv_parsing.py $(OUTDIR)/cv.pdf
	./check_cv_parsing.py $(OUTDIR)/cv-tech.pdf

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

# assets/profile-pic-web.png is not embedded, but its size feeds the footer's
# page-weight figure, so a re-dithered avatar has to re-render the page too.
$(OUTDIR)/index.html: styles.css $(wildcard assets/*.svg) $(BLDDIR)/favicon.png.b64 \
	templates/_head.html templates/_footer.html assets/superscript.csl \
	assets/profile-pic-web.png

%.pdf: %.tex FORCE
	latexmk -shell-escape -f -pdfxe -outdir=$(dir $@) -interaction=nonstopmode $<

$(OUTDIR) $(BLDDIR):
	mkdir -p $@

# Regenerate the committed homepage avatar from the full-resolution source.
# The homepage only needs a small thumbnail (displayed at 160px, 2x for retina),
# whereas assets/profile-pic.jpeg stays large for the CV PDF (embedded at print
# size). Floyd-Steinberg dithering to one bit takes the thumbnail from 10.6 kB
# to 3.2 kB and is what gives it the halftone look; PNG is the container to pair
# it with, since JPEG would ring around the dither pattern and encode larger.
# `-colors 2 -type Bilevel` selects the error-diffusion path — note that
# `-monochrome` looks similar but is a different algorithm and flattens the
# shading to near line art. The result is committed and copied by the normal
# build, so CI needs no image tooling; run this by hand (needs ImageMagick, e.g.
# `apt-get install imagemagick`) only when the source photo changes.
avatar:
	convert assets/profile-pic.jpeg -auto-orient -strip -resize 320x320 \
		-colorspace Gray -dither FloydSteinberg -colors 2 -type Bilevel -depth 1 \
		-define png:compression-level=9 assets/profile-pic-web.png

clean:
	rm -rf $(BLDDIR) $(OUTDIR)

distclean: clean
	rm -f .cache.json

FORCE:

dev:
	printf '%s\n' render.py templates/index.html.in templates/_head.html templates/_footer.html $(wildcard data/*) templates/styles.css | entr make $(OUTDIR)/index.html & \
	printf '%s\n' posts.py render.py templates/post.html.in templates/blog.html.in templates/_head.html templates/_footer.html templates/styles.css $(POSTS) | entr make $(OUTDIR)/notes/index.html & \
	printf '%s\n' render.py templates/cv-academic.txt.in $(wildcard data/*) | entr make $(OUTDIR)/cv-academic.txt & \
	printf '%s\n' render.py templates/cv-academic.tex.in $(wildcard data/*) | entr make $(OUTDIR)/cv-academic.pdf & \
	printf '%s\n' render.py templates/cv.tex.in $(wildcard data/*) | entr make $(OUTDIR)/cv.pdf & \
	printf '%s\n' render.py templates/cv-tech.tex.in $(wildcard data/*) | entr make $(OUTDIR)/cv-tech.pdf & \
	python3 -m http.server -b 0.0.0.0 -d $(OUTDIR)
