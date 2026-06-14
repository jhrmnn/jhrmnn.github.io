<!--
The homepage spine: only the per-section headings and prose live here; the tool
list, publications and talks are injected by render.py. Each section is a dense
narrative paragraph with [@key] citations to publications — its publication list
is exactly the works its prose cites, numbered consecutively across all sections
(render.py runs the whole file through pandoc + citeproc in one pass). The lead
paragraph before the first heading is the homepage intro. Header attributes carry
the anchor id and, for a hub, its GitHub repo, shown in the heading with its star
count; the `.theme` section instead gets an injected list of every tool not
anchored to a hub. A paper appears under a section because the prose cites it —
cross-list by citing it in both. The software/tool list and talks live in
data/cv.yaml. See issue #50.
-->

I build quantum-chemistry tools that others build on, tracing an arc from
hand-crafted physics modeling of van der Waals dispersion, to physics-driven
machine learning of wavefunctions, to data-driven machine learning of the
exchange–correlation functional.

# Density functional theory {#Skala github="microsoft/skala"}

Exchange–correlation, learned from data. Skala learns the
exchange–correlation functional of Kohn–Sham DFT, reaching hybrid-functional
accuracy at semi-local cost [@Luise25]. This thread started by looking at the algorithmic side of things
[@delMazo-SevillanoJCP23], but it later became evident that the key ingredient is data [@EhlertSD26; @GasevicJCIM25].

# Quantum Monte Carlo {#DeepQMC github="deepqmc/deepqmc"}

Wavefunctions, learned from physics. Deep QMC began with PauliNet
[@HermannNC20], the first deep-learning *ansatz* to reach chemical accuracy through
variational Monte Carlo — the wavefunction optimized against the Schrödinger
equation itself, with no reference data. It can be converged to the fixed-node limit
[@SchatzleJCP21], reach excited states [@EntwistleNC23], and eventually grew into a general
open-source suite [@SchatzleJCP23] within a fast-developing field [@HermannNRC23].
Those same wavefunctions also yield accurate real-space electron densities
[@ChengJCP25], and in the latest iteration are encoded in a single foundation model
[@Foster25].

# Van der Waals dispersion {#libMBD github="libmbd/libmbd"}

Long-range electron corelation, by hand. The itch started with a vdW-DF/CCSD(T)
correction scheme [@HermannJCP13; @Hermann13] for zeolites [@HermannCT14; @PolozijCT13] and grew
into a unified density-functional model of van der Waals interactions
[@HermannPRL20; @Hermann18; @HermannCR17], with the exchange–correlation
balance worked out along the way [@HermannJCTC18; @Hermann18a]. Packaged as
libMBD, a scalable many-body dispersion library [@HermannJCP23] now
embedded in several electronic-structure codes, it underpins applications from π–π
stacked molecules [@HermannNC17] through molecular crystals and layered materials
[@LiuJCP16; @ChattopadhyayaCM17; @CuiJPCL20; @OuyangJCTC21] to Casimir and
fluctuational-electrodynamics phenomena [@VenkataramPRL17; @VenkataramPRL18;
@VenkataramSA19; @VenkataramPRB20; @StohrNC21].

# Codes, tools & writing {#more .theme}

Beyond the three flagships, the connective tissue. I build standalone tools and
[Mona](https://pub.hrmnn.net/ec/8024310f/2018-11-28-fhi-talk.pdf), a framework for
reproducible computational science, and contribute to community
electronic-structure codes, each with its own program paper [@Abbott25; @SunJCP20;
@HourahineJCP20; @SmithJCP21]. The same breadth runs through survey writing, from a
roadmap on machine learning in electronic structure [@KulikES22] to an introduction
to material modeling [@Hermann20], and the assorted invited seminars below.
