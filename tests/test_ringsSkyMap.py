import unittest
import math

import lsst.utils.tests
import lsst.afw.coord
import lsst.afw.geom

from lsst.skymap.ringsSkyMap import RingsSkyMap
from helper import skyMapTestCase


class RingsTestCase(skyMapTestCase.SkyMapTestCase):

    def setUp(self):
        config = RingsSkyMap.ConfigClass()
        config.numRings = 3
        self._NumTracts = 26  # Number of tracts to expect
        self._NeighborAngularSeparation = None  # Expected tract separation
        self._SkyMapClass = RingsSkyMap  # Class of SkyMap to test
        self._SkyMapConfig = config  # Configuration to use
        self._SkyMapName = "rings"  # Name of SkyMap class to test
        self._numNeighbors = None  # Number of neighbours

    def testTractSeparation(self):
        self.skipTest("A particular tract separation is not important for RingsSkyMap")

    def testPoles(self):
        """Test that findAllTracts behaves at the poles

        Testing fix to DM-10686.
        """
        skymap = self.getSkyMap()
        deg = lsst.afw.geom.degrees
        for ra in (0, 123, 321, 359.9):
            tracts = skymap.findAllTracts(lsst.afw.coord.IcrsCoord(ra*deg, 90*deg))
            self.assertListEqual(tracts, [skymap[len(skymap) - 1]])
            tracts = skymap.findAllTracts(lsst.afw.coord.IcrsCoord(ra*deg, -90*deg))
            self.assertListEqual(tracts, [skymap[0]])

    def testSha1Compare(self):
        """Test that RingsSkyMap's extra state is included in its hash."""
        defaultSkyMap = self.getSkyMap()
        for numRings in (4, 5):
            config = self.getConfig()
            config.numRings = numRings
            skyMap = self.getSkyMap(config=config)
            self.assertNotEqual(skyMap, defaultSkyMap)
        for raStart in (60.0, 75.0):
            config = self.getConfig()
            config.raStart = raStart
            skyMap = self.getSkyMap(config=config)
            self.assertNotEqual(skyMap, defaultSkyMap)

    def testCorners(self):
        """Test that corners of a tract can be found in the tract"""
        skymap = self.getSkyMap()
        for tract in skymap:
            vertices = tract.getVertexList()
            for coord in vertices:
                self.assertIn(tract.getId(), [tt.getId() for tt in skymap.findAllTracts(coord)])


class NonzeroRaStartRingsTestCase(RingsTestCase):
    """Test that setting raStart != 0 works"""
    def getConfig(self):
        config = super().getConfig()
        config.raStart = 234
        return config


class HscRingsTestCase(lsst.utils.tests.TestCase):
    def getConfig(self):
        """Return a configuration matching that used for the HSC SSP"""
        config = RingsSkyMap.ConfigClass()
        config.numRings = 120
        config.projection = "TAN"
        config.tractOverlap = 1.0/60  # Overlap between tracts (degrees)
        config.pixelScale = 0.168
        return config

    def setUp(self):
        self.skymap = RingsSkyMap(self.getConfig())

    def tearDown(self):
        del self.skymap

    def testDm7770(self):
        """Test that DM-7770 has been fixed

        These operations previously caused:
            lsst::pex::exceptions::RuntimeError: 'Error: wcslib
            returned a status code of 9 at sky 30.18, -3.8 deg:
            One or more of the world coordinates were invalid'

        We are only testing function, and not the actual results.
        """
        coordList = [lsst.afw.coord.IcrsCoord(ra*lsst.afw.geom.degrees, dec*lsst.afw.geom.degrees) for
                     ra, dec in [(30.18, -3.8), (31.3, -3.8), (31.3, -2.7), (30.18, -2.7)]]
        for coord in coordList:
            self.skymap.findAllTracts(coord)
        self.skymap.findTractPatchList(coordList)

    def testDm14809(self):
        """Test that DM-14809 has been fixed"""
        skyMapTestCase.checkDm14809(self, self.skymap)

        # Check that the first tract in the last ring exists
        coord = self.getFirstTractLastRingCoord()
        tract = self.skymap.findTract(coord)
        self.assertTrue(tract.contains(coord))

    def testWraparound(self):
        """Check wrapping at RA=0

        How-to-reproduce of a bug identified by Sogo Mineo.
        """
        tractId = 9712
        deviation = 10 / 3600.0  # 10 arcsec
        tract = self.skymap[tractId]
        center = tract.getCtrCoord()
        centerRa = center.getRa().asDegrees()
        centerDec = center.getDec().asDegrees()
        for devRa in [-deviation, deviation]:
            coord = lsst.afw.coord.IcrsCoord(lsst.afw.geom.Point2D(centerRa + devRa, centerDec),
                                             lsst.afw.geom.degrees)
            foundTractId = self.skymap.findTract(coord).getId()
            self.assertEqual(tractId, foundTractId)

    def getFirstTractLastRingCoord(self):
        """Return the coordinates of the first tract in the last ring

        This tract is missing in version=0, but this is fixed in version=1.in
        """
        ringNum = self.skymap.config.numRings - 1
        ringSize = math.pi/(self.skymap.config.numRings + 1)
        firstRingStart = ringSize*0.5 - 0.5*math.pi
        dec = ringNum*ringSize + firstRingStart
        return lsst.afw.coord.IcrsCoord(self.skymap.config.raStart*lsst.afw.geom.degrees,
                                        dec*lsst.afw.geom.radians)


class Version0HscRingsTestCase(HscRingsTestCase):
    """Testing that the version=0 RingsSkyMap works in the expected way"""
    def setUp(self):
        self.skymap = RingsSkyMap(self.getConfig(), version=0)

    def testDm14809(self):
        """Test that DM-14809 has been partially fixed

        The observed behaviour was:

            skyMap.findTract(skyMap[9712].getCtrCoord()).getId() != 9712

        and

            skyMap[1].getCtrCoord() == skyMap[11].getCtrCoord()

        Specifically for version=0, we fixed the ``findTract`` behaviour but
        left the tract duplication (tract 11 duplicates tract 1) and the
        missing tract (the first tract in the last ring) so that the tract
        numbering would remain unchanged.
        """
        # Check that the tract found for central coordinate of a tract is that tract
        expect = [tract.getId() for tract in self.skymap]
        expect[self.skymap._ringNums[0] + 1] = 1  # Due to the bug
        got = [self.skymap.findTract(tract.getCtrCoord()).getId() for tract in self.skymap]
        self.assertEqual(got, expect)

        # Check that the tract central coordinates are unique
        # Round to integer arcminutes so differences are relatively immune to small numerical inaccuracies
        centers = set([(int(coord.getRa().asArcminutes()), int(coord.getDec().asArcminutes())) for
                       coord in (tract.getCtrCoord() for tract in self.skymap)])
        self.assertEqual(len(centers), len(self.skymap) - 1)  # One tract is duplicated
        self.assertEqual(self.skymap[1].getCtrCoord(),
                         self.skymap[self.skymap._ringNums[0] + 1].getCtrCoord())  # This is the duplicate

        # Check that some particular tracts we know and love haven't moved
        degrees = lsst.afw.geom.degrees
        # 9712 is at RA=0, and was identified as problematic in DM-14809
        self.assertEqual(self.skymap[9712].getCtrCoord(),
                         lsst.afw.coord.IcrsCoord(0.0*degrees, 0.7438016528925696*degrees))
        # The Cosmos field
        self.assertEqual(self.skymap[9813].getCtrCoord(),
                         lsst.afw.coord.IcrsCoord(150.2479338842975*degrees, 2.2314049586776834*degrees))

        # Check that the first tract in the last ring does NOT exist (due to the bug)
        coord = self.getFirstTractLastRingCoord()
        tract = self.skymap.findTract(coord)
        self.assertFalse(tract.contains(coord))


class MemoryTester(lsst.utils.tests.MemoryTestCase):
    pass


def setup_module(module):
    lsst.utils.tests.init()


if __name__ == "__main__":
    lsst.utils.tests.init()
    unittest.main()
