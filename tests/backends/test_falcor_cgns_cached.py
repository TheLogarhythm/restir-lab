"""Regression checks for the private CGNS producer/consumer contract."""
from pathlib import Path
import unittest

from scripts.falcor import cgns_cached_overlay as overlay, cgns_cached_runtime as runtime
from scripts.falcor.spatial_experiment_config import load_config


class CachedCgnsTests(unittest.TestCase):
    def test_cache_only_substitutes_geometry_inputs(self):
        params = load_config()['methods']['cgns']['shader']
        direct = overlay.selector(params, cached=False)
        cached = overlay.selector(params, cached=True)
        # Random draws, traversal order, duplicate rejection, and WRS must
        # remain shared with the legacy oracle for every configurable K.
        for token in ('uint seed=', 'bool duplicate=', 'float score=', 'LabCgnsSingleInsert(reservoir,'):
            self.assertEqual(next(line for line in direct.splitlines() if token in line),
                             next(line for line in cached.splitlines() if token in line))
        self.assertNotIn('getPixelShadingData(', cached)
        self.assertEqual(direct.count('getPixelShadingData('), 2)

    def test_all_consumers_address_by_central_pixel_and_round(self):
        upstream = runtime.MODULES / 'ReSTIRPathTracing'
        if not (upstream / 'ReSTIRPathTracing.cpp').exists():
            self.skipTest('requires the Falcor submodule')
        params = load_config()['methods']['cgns']['shader']
        # Map deployment shader paths onto the pinned source tree. No runtime
        # build or GPU is needed to exercise the production overlay.
        class PinnedSource:
            def __truediv__(self, name):
                return upstream / Path(name).name
        shaders = overlay.shader_outputs(PinnedSource(), params)
        for name, count in overlay.CONSUMERS.items():
            code = shaders[(overlay.MODULE / name).as_posix()]
            self.assertEqual(code.count('decodeCgnsNeighbor(cgnsNeighbors[pixel],'), count)
            self.assertNotIn('labCgnsSelectPointNeighbors(', code)
        host = overlay.host_sources(upstream)['ReSTIRPathTracing.cpp']
        body = host.split('void ReSTIRPathTracing::spatialResampling(', 1)[1]
        self.assertLess(body.index('cacheCgnsAttributes('), body.index('for (uint32_t iteration'))
        self.assertLess(body.index('for (uint32_t iteration'), body.index('selectCgnsNeighbors('))
        self.assertLess(body.index('selectCgnsNeighbors('), body.index('spatialDispatchGenerateRetraceWorkload('))
        self.assertEqual(body.count('["cgnsNeighbors"] = mpCgnsNeighbors;'), 3)
