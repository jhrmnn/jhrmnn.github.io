BLDDIR = build

default: cv

cv: cv.pdf cv.html cv.txt

$(BLDDIR)/%.pdf $(BLDDIR)/%.bbl: %.tex FORCE
	latexmk -shell-escape -f -pdfxe -outdir=$(BLDDIR) -interaction=nonstopmode $<

$(BLDDIR)/cv.pdf: profile-pic.png

cv.tex: render.py cv.tex.in cv.yaml refs.json extras.yaml
	python3 $^ $(FLAGS) >$@

cv.html: render.py cv.html.in cv.yaml refs.json extras.yaml styles.css $(wildcard *.svg)
	python3 $(wordlist 1,5,$^) $(FLAGS) >$@

cv.txt: render.py cv.txt.in cv.yaml refs.json extras.yaml
	python3 $^ $(FLAGS) >$@

profile-pic.png:
	cp profile-pic-public.png $@

refs.json:
	-curl -sf "http://localhost:23119/better-bibtex/collection?/1/ZMy%20Publications.csljson" >$@

%: $(BLDDIR)/%
	cp $^ $@

clean:
	rm -rf $(BLDDIR)
	rm -f cv.pdf cv.tex cv.html cv.txt .cache.json

FORCE:

dev:
	ls render.py cv.html.in cv.yaml refs.json extras.yaml styles.css | entr make cv.html & \
	ls render.py cv.txt.in cv.yaml refs.json extras.yaml | entr make cv.txt & \
	ls render.py cv.tex.in cv.yaml refs.json extras.yaml | entr make cv.pdf & \
	python3 -m http.server -b 0.0.0.0
