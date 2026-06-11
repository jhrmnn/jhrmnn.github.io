<!--
The homepage spine: one section per tool-hub plus a final `.theme` section, each
a dense narrative paragraph with [@key] citations. The section's reference list is
exactly the works its prose cites; numbering runs consecutively across all sections
(render.py runs this through pandoc + citeproc). Header attributes carry the anchor
id and, for a hub, its GitHub repo (for the repo link and star count, looked up in
data/cv.yaml's software list). A paper appears under a section because the prose
cites it — cross-list by citing it in both. The software/tool list, talks and
program papers live in data/cv.yaml. See issue #50.
-->

# Skala {#Skala github="microsoft/skala"}

Machine-learned exchange–correlation. [Skala](https://github.com/microsoft/skala)
learns the exchange–correlation functional of Kohn–Sham DFT directly from data,
reaching hybrid-functional accuracy at semi-local cost [@Luise25]. The thread runs
through a variational principle for regularizing machine-learned density
functionals [@delMazo-SevillanoJCP23] and ties back to wavefunctions via accurate
real-space electron densities from neural networks [@ChengJCP25], trained and
benchmarked on dedicated reference datasets [@EhlertSD26; @GasevicJCIM25].

# DeepQMC {#DeepQMC github="deepqmc/deepqmc"}

Neural-network wavefunctions. [DeepQMC](https://github.com/deepqmc/deepqmc) began with
PauliNet [@HermannNC20], the first deep-learning *ansatz* to reach chemical accuracy
through variational Monte Carlo; it converged to the fixed-node limit [@SchatzleJCP21],
reached excited states [@EntwistleNC23], and grew into a general open-source suite
[@SchatzleJCP23] (with a review of the field [@HermannNRC23]). Those wavefunctions also
yield accurate real-space electron densities [@ChengJCP25], and the arc now points at a
foundation model of wavefunctions [@Foster25].

# libMBD {#libMBD github="libmbd/libmbd"}

Many-body dispersion and van der Waals interactions. The itch started with a
vdW-DF/CCSD(T) correction scheme [@HermannJCP13] for zeolites [@HermannCT14;
@PolozijCT13] and grew into a unified density-functional model of van der Waals
interactions [@HermannPRL20] — two theses [@Hermann13; @Hermann18] and a *Chemical
Reviews* survey [@HermannCR17], with the exchange–correlation balance worked out along
the way [@HermannJCTC18; @Hermann18a]. Packaged as
[libMBD](https://github.com/libmbd/libmbd), a scalable many-body dispersion library
[@HermannJCP23] now embedded in several electronic-structure codes, it underpins
applications from π–π stacked molecules [@HermannNC17] through molecular crystals and
layered materials [@LiuJCP16; @ChattopadhyayaCM17; @CuiJPCL20; @OuyangJCTC21] to Casimir
and fluctuational-electrodynamics phenomena [@VenkataramPRL17; @VenkataramPRL18;
@VenkataramSA19; @VenkataramPRB20; @StohrNC21].

# Codes, tools & writing {#more .theme}

Beyond the three flagships, the connective tissue. I build smaller standalone
tools — Pyberny [@pyberny], a molecular geometry optimizer, and
[Mona](https://pub.hrmnn.net/ec/8024310f/2018-11-28-fhi-talk.pdf), a framework for
reproducible computational science — and contribute to the community
electronic-structure codes the methods above plug into: FHI-aims [@fhiaims],
PySCF [@pyscf], DFTB+ [@dftbplus], and QCEngine [@qcengine]. The same breadth runs
through survey writing, from a roadmap on machine learning in electronic structure
[@KulikES22] to an introduction to material modeling [@Hermann20], and the assorted
invited seminars below.
