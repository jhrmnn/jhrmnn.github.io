BLDDIR = build

default: cv

cv: cv.pdf cv.html cv.txt

$(BLDDIR)/%.pdf $(BLDDIR)/%.bbl: %.tex FORCE
	latexmk -shell-escape -f -pdfxe -outdir=$(BLDDIR) -interaction=nonstopmode $<

$(BLDDIR)/cv.pdf: profile-pic.png

cv.tex: render.py cv.tex.in cv.yaml refs.json extras.yaml
	python3 $^ $(FLAGS) -o $@

cv.html: render.py cv.html.in cv.yaml refs.json extras.yaml styles.css $(wildcard *.svg)
	python3 $(wordlist 1,5,$^) $(FLAGS) -o $@

cv.txt: render.py cv.txt.in cv.yaml refs.json extras.yaml
	python3 $^ $(FLAGS) -o $@

profile-pic.png:
	cp profile-pic-public.png $@

%: $(BLDDIR)/%
	cp $^ $@

clean:
	rm -rf $(BLDDIR)
	rm -f cv.pdf cv.tex cv.html cv.txt

distclean: clean
	rm -f .cache.json

FORCE:

dev:
	ls render.py cv.html.in cv.yaml refs.json extras.yaml styles.css | entr make cv.html & \
	ls render.py cv.txt.in cv.yaml refs.json extras.yaml | entr make cv.txt & \
	ls render.py cv.tex.in cv.yaml refs.json extras.yaml | entr make cv.pdf & \
	python3 -m http.server -b 0.0.0.0
