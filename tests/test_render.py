"""Snapshot test for the rendering pipeline.

Renders the plain-text CV from the real data files and compares it against a
committed snapshot, so regressions in the templating / markdown-conversion
logic are caught without needing the network or a LaTeX toolchain.

The web-enrichment step (citation counts, GitHub stars, Scholar, Publons) is
stubbed out, since it depends on flaky external services. As a result the
``NUMREV`` placeholder in the "activity" section is left unsubstituted in the
snapshot -- that is expected.

To regenerate the snapshot after an intentional change::

    UPDATE_SNAPSHOTS=1 poetry run python -m unittest discover -s tests
"""
import os
import unittest
from pathlib import Path
from unittest import mock

import render

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = Path(__file__).resolve().parent / 'snapshots' / 'cv.txt'
DATA = [
    REPO_ROOT / 'data' / 'cv.yaml',
    REPO_ROOT / 'data' / 'extras.yaml',
    REPO_ROOT / 'data' / 'refs.json',
]
# Relative so Jinja's FileSystemLoader (rooted at '.') can find it; the test
# chdirs to the repo root, matching how the Makefile invokes render.py.
TEMPLATE = Path('templates/cv.txt.in')


class CvTxtSnapshotTest(unittest.TestCase):
    def setUp(self):
        self._cwd = Path.cwd()
        os.chdir(REPO_ROOT)
        # render() builds a Jinja loader from ['.', $BLDDIR]; give it a value.
        self._blddir = os.environ.get('BLDDIR')
        os.environ['BLDDIR'] = self._blddir or 'build'

    def tearDown(self):
        os.chdir(self._cwd)
        if self._blddir is None:
            os.environ.pop('BLDDIR', None)
        else:
            os.environ['BLDDIR'] = self._blddir

    def _render(self):
        # Skip the network-dependent enrichment step for determinism.
        with mock.patch.object(render, 'update_from_web', lambda ctx, cache: None):
            return render.render(TEMPLATE, DATA).decode('ascii')

    def test_cv_txt_matches_snapshot(self):
        rendered = self._render()
        if os.environ.get('UPDATE_SNAPSHOTS'):
            SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
            SNAPSHOT.write_text(rendered)
            self.skipTest('snapshot updated')
        self.assertTrue(
            SNAPSHOT.exists(),
            f'missing snapshot {SNAPSHOT}; run with UPDATE_SNAPSHOTS=1 to create it',
        )
        self.assertEqual(rendered, SNAPSHOT.read_text())


if __name__ == '__main__':
    unittest.main()
