#!/usr/bin/env python

# 
# LSST Data Management System
# Copyright 2008, 2009, 2010 LSST Corporation.
# 
# This product includes software developed by the
# LSST Project (http://www.lsst.org/).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the LSST License Statement and 
# the GNU General Public License along with this program.  If not, 
# see <http://www.lsstcorp.org/LegalNotices/>.
#

"""Test SkyMap class
"""
import os
import sys
import math
import unittest

import numpy

import lsst.utils.tests as utilsTests
import lsst.pex.policy as pexPolicy
import lsst.pex.policy as pexPolicy
import lsst.afw.coord as afwCoord
import lsst.afw.geom as afwGeom
import lsst.skymap as skymap

_RadPerDeg = math.pi / 180.0

# dodecahedron properties
_NumTracts = 12
_Phi = (1.0 + math.sqrt(5.0)) / 2.0
_DihedralAngle = 2.0 * math.atan(_Phi) / _RadPerDeg
_NeighborAngularSeparation = 180.0 - _DihedralAngle

class DodecaSkyMapTestCase(unittest.TestCase):
    def testBasicAttributes(self):
        """Confirm that constructor attributes are available
        """
        sm = skymap.DodecaSkyMap()
        self.assertEqual(len(sm), _NumTracts)
        self.assertEqual(sm.getOverlap(), 3.5 * _RadPerDeg)
        self.assertEqual(sm.getProjection(), "STG")
        
        for overlap in (0.0, 0.01, 0.1): # degrees
            sm = skymap.DodecaSkyMap(overlap = afwGeom.Angle(overlap, afwGeom.degrees))
            self.assertEqual(sm.getOverlap().asDegrees(), overlap)
            for tractInfo in sm:
                self.assertAlmostEqual(tractInfo.getOverlap().asDegrees(), overlap)
        
        for pixelScale in (0.01, 0.1, 1.0): # arcseconds/pixel
            sm = skymap.DodecaSkyMap(pixelScale = afwGeom.Angle(pixelScale, afwGeom.arcseconds))
            self.assertAlmostEqual(sm.getPixelScale().asArcseconds(), pixelScale)
        
        for projection in ("STG", "TAN", "MOL"):
            sm = skymap.DodecaSkyMap(projection = projection)
            self.assertEqual(sm.getProjection(), projection)
    
    def testTractSeparation(self):
        """Confirm that each sky tract has the proper distance to other tracts
        """
        sm = skymap.DodecaSkyMap()
        for tractId, tractInfo in enumerate(sm):
            self.assertEqual(tractInfo.getId(), tractId)
        
            ctrCoord = tractInfo.getCtrCoord()
            distList = []
            for tractInfo1 in sm:
                otherCtrCoord = tractInfo1.getCtrCoord()
                distList.append(ctrCoord.angularSeparation(otherCtrCoord).asDegrees())
            distList.sort()
            self.assertAlmostEquals(distList[0], 0.0)
            for dist in distList[1:6]:
                self.assertAlmostEquals(dist, _NeighborAngularSeparation)
            self.assertAlmostEquals(distList[11], 180.0)
    
    def testFindTract(self):
        """Test the findTract method
        """
        sm = skymap.DodecaSkyMap()
        for tractInfo0 in sm:
            tractId0 = tractInfo0.getId()
            ctrCoord0 = tractInfo0.getCtrCoord()
            vector0 = numpy.array(ctrCoord0.getVector())
            
            # make a list of all 5 nearest neighbors
            nbrTractList = []
            for otherTractInfo in sm:
                otherCtrCoord = otherTractInfo.getCtrCoord()
                dist = ctrCoord0.angularSeparation(otherCtrCoord).asDegrees()
                if abs(dist - _NeighborAngularSeparation) < 0.1:
                    nbrTractList.append(otherTractInfo)
            self.assertEqual(len(nbrTractList), 5)
            
            for tractInfo1 in nbrTractList:
                tractId1 = tractInfo1.getId()
                ctrCoord1 = tractInfo1.getCtrCoord()
                vector1 = numpy.array(ctrCoord1.getVector())
                for tractInfo2 in nbrTractList[tractInfo1.getId():]:
                    dist = ctrCoord1.angularSeparation(tractInfo2.getCtrCoord()).asDegrees()
                    if abs(dist - _NeighborAngularSeparation) > 0.1:
                        continue
                    tractId2 = tractInfo2.getId()
                    ctrCoord2 = tractInfo2.getCtrCoord()
                    vector2 = numpy.array(ctrCoord2.getVector())
                
                    # sky tracts 0, 1 and 2 form a triangle of nearest neighbors
                    # explore the boundary between tract 0 and tract 1
                    # and also the boundary between tract 0 and tract 2
                    for deltaFrac in (-0.001, 0.001):
                        isNearest0 = deltaFrac > 0.0
                        
                        for exploreBoundary1 in (True, False):
                            # if exploreBoundary1, explore boundary between tract 0 and tract 1,
                            # else explore the boundary between tract 0 and tract 2
                        
                            if isNearest0:
                                expectedTractId = tractId0
                            elif exploreBoundary1:
                                expectedTractId = tractId1
                            else:
                                expectedTractId = tractId2
                            
                            for farFrac in (0.0, 0.05, 0.3, (1.0/3.0) - 0.01):
                                # farFrac is the fraction of the tract center vector point whose boundary
                                # is not being explored; it must be less than 1/3;
                                # remFrac is the remaining fraction, which is divided between tract 0
                                # and the tract whose boundary is being explored
                                remFrac = 1.0 - farFrac
                                frac0 = (remFrac / 2.0) + deltaFrac
                                boundaryFrac = (remFrac / 2.0) - deltaFrac
                                
                                if exploreBoundary1:
                                    frac2 = farFrac
                                    frac1 = boundaryFrac
                                else:
                                    frac1 = farFrac
                                    frac2 = boundaryFrac
    
                                testVector = (vector0 * frac0) + (vector1 * frac1) + (vector2 * frac2)
                                vecLen = math.sqrt(numpy.sum(testVector**2))
                                testVector /= vecLen
                                lsstVec = afwGeom.Point3D(testVector)
                                testCoord = afwCoord.IcrsCoord(lsstVec)
                                nearestTractInfo = sm.findTract(testCoord)
                                nearestTractId = nearestTractInfo.getId()
    
                                if expectedTractId != nearestTractId:
                                    nearestCtrCoord = nearestTractInfo.getCtrCoord()
                                    nearestVector = nearestCtrCoord.getVector()
    
                                    print "tractId0=%s; tractId1=%s; tractId2=%s; nearestTractId=%s" % \
                                        (tractId0, tractId1, tractId2, nearestTractId)
                                    print "vector0=%s; vector1=%s; vector2=%s; nearestVector=%s" % \
                                         (vector0, vector1, vector2, nearestVector)
                                    print "frac0=%s; frac1=%s; frac2=%s" % (frac0, frac1, frac2)
                                    print "testVector=", testVector
    
                                    print "dist0=%s; dist1=%s; dist2=%s; nearDist=%s" % (
                                        testCoord.angularSeparation(ctrCoord0).asDegrees(),
                                        testCoord.angularSeparation(ctrCoord1).asDegrees(),
                                        testCoord.angularSeparation(ctrCoord2).asDegrees(),
                                        testCoord.angularSeparation(nearestCtrCoord).asDegrees(),
                                    )
                                    self.fail("Expected nearest tractId=%s; got tractId=%s" % \
                                        (expectedTractId, nearestTractId))
                    


def suite():
    """Return a suite containing all the test cases in this module.
    """
    utilsTests.init()

    suites = [
        unittest.makeSuite(DodecaSkyMapTestCase),
        unittest.makeSuite(utilsTests.MemoryTestCase),
    ]

    return unittest.TestSuite(suites)


def run(shouldExit=False):
    """Run the tests"""
    utilsTests.run(suite(), shouldExit)

if __name__ == "__main__":
    run(True)
