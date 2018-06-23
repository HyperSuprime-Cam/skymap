from builtins import range
#
# LSST Data Management System
# Copyright 2008, 2009, 2010, 2012 LSST Corporation.
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

import struct
import math

from lsst.pex.config import Field
from lsst.afw.coord import IcrsCoord
import lsst.afw.geom as afwGeom
from .cachingSkyMap import CachingSkyMap
from .tractInfo import ExplicitTractInfo

__all__ = ["RingsSkyMapConfig", "RingsSkyMap"]


class RingsSkyMapConfig(CachingSkyMap.ConfigClass):
    """Configuration for the RingsSkyMap"""
    numRings = Field(dtype=int, doc="Number of rings", check=lambda x: x > 0)
    raStart = Field(dtype=float, default=0.0, doc="Starting center RA for each ring (degrees)",
                    check=lambda x: x >= 0.0 and x < 360.0)


class RingsSkyMap(CachingSkyMap):
    """Rings sky map pixelization.

    We divide the sphere into N rings of Declination, plus the two polar
    caps, which sets the size of the individual tracts.  The rings are
    divided in RA into an integral number of tracts of this size; this
    division is made at the Declination closest to zero so as to ensure
    full overlap.

    Rings are numbered in the rings from south to north. The south pole cap is
    ``tract=0``, then the tract at ``raStart`` in the southernmost ring is
    ``tract=1``. Numbering continues (in the positive RA direction) around that
    ring and then continues in the same fashion with the next ring north, and
    so on until all reaching the north pole cap, which is
    ``tract=len(skymap) - 1``.

    However, ``version=0`` had a bug in the numbering of the tracts: the first
    and last tracts in the first (southernmost) ring were identical, and the
    first tract in the last (northernmost) ring was missing. When using
    ``version=0``, these tracts remain missing in order to preserve the
    numbering scheme.

    Parameters
    ----------
    config : `lsst.skymap.RingsSkyMapConfig`
        Configuration for this skymap.
    version : `int`, optional
        Software version of this class, to retain compatibility with old
        verisons. ``version=0`` covers the period from first implementation
        until DM-14809, at which point bugs were identified in the numbering
        of tracts (affecting only tracts at RA=0). ``version=1`` uses the
        post-DM-14809 tract numbering.
    """
    ConfigClass = RingsSkyMapConfig
    _version = (1, 0)  # for pickle

    def __init__(self, config, version=1):
        """Constructor"""
        assert version in (0, 1), "Unrecognised version: %s" % (version,)
        # We count rings from south to north
        # Note: pole caps together count for one additional ring when calculating the ring size
        self._ringSize = math.pi / (config.numRings + 1)  # Size of a ring in Declination (radians)
        self._ringNums = []  # Number of tracts for each ring
        for i in range(config.numRings):
            startDec = self._ringSize*(i + 0.5) - 0.5*math.pi
            stopDec = startDec + self._ringSize
            dec = min(math.fabs(startDec), math.fabs(stopDec))  # Declination for determining division in RA
            self._ringNums.append(int(2*math.pi*math.cos(dec)/self._ringSize) + 1)
        numTracts = sum(self._ringNums) + 2
        super(RingsSkyMap, self).__init__(numTracts, config, version)
        self._raStart = self.config.raStart*afwGeom.degrees

    def getRingIndices(self, index):
        """Calculate ring indices given a numerical index of a tract

        The ring indices are the ring number and the tract number within
        the ring.

        The ring number is -1 for the south polar cap and increases to the
        north.  The north polar cap has ring number = numRings.  The tract
        number is zero for either of the polar caps.
        """
        if index == 0:  # South polar cap
            return -1, 0
        if index == self._numTracts - 1:  # North polar cap
            return self.config.numRings, 0
        if index < 0 or index >= self._numTracts:
            raise IndexError("Tract index %d is out of range [0, %d]" % (index, len(self) - 1))
        ring = 0  # Ring number
        tractNum = index - 1  # Tract number within ring
        if self._version == 0:
            # Maintain the off-by-one bug in version=0 (DM-14809).
            # This means that the first tract in the first ring is duplicated
            # and the first tract in the last ring is missing.
            while ring < self.config.numRings and tractNum > self._ringNums[ring]:
                tractNum -= self._ringNums[ring]
                ring += 1
        else:
            while ring < self.config.numRings and tractNum >= self._ringNums[ring]:
                tractNum -= self._ringNums[ring]
                ring += 1
        return ring, tractNum

    def generateTract(self, index):
        """Generate the TractInfo for this index"""
        ringNum, tractNum = self.getRingIndices(index)
        if ringNum == -1:  # South polar cap
            ra, dec = 0, -0.5*math.pi
        elif ringNum == self.config.numRings:  # North polar cap
            ra, dec = 0, 0.5*math.pi
        else:
            dec = self._ringSize*(ringNum + 1) - 0.5*math.pi
            ra = ((2*math.pi*tractNum/self._ringNums[ringNum])*afwGeom.radians +
                  self._raStart).wrap().asRadians()

        center = IcrsCoord(ra*afwGeom.radians, dec*afwGeom.radians)
        wcs = self._wcsFactory.makeWcs(crPixPos=afwGeom.Point2D(0, 0), crValCoord=center)
        return ExplicitTractInfo(index, self.config.patchInnerDimensions, self.config.patchBorder, center,
                                 0.5*self._ringSize*afwGeom.radians, self.config.tractOverlap*afwGeom.degrees,
                                 wcs)

    def _decToRingNum(self, dec):
        """Calculate ring number from Declination

        Parameters
        ----------
        dec : `lsst.afw.geom.Angle`
            Declination.

        Returns
        -------
        ringNum : `int`
            Ring number: -1 for the south polar cap, and increasing to the
            north, ending with ``numRings`` for the north polar cap.
        """
        firstRingStart = self._ringSize*0.5 - 0.5*math.pi
        if dec < firstRingStart:
            # Southern cap
            return -1
        elif dec > firstRingStart*-1:
            # Northern cap
            return self.config.numRings
        return int((dec.asRadians() - firstRingStart)/self._ringSize)

    def _raToTractNum(self, ra, ringNum):
        """Calculate tract number from the Right Ascension

        Parameters
        ----------
        ra : `lsst.afw.geom.Angle`
            Right Ascension.
        ringNum : `int`
            Ring number (from ``_decToRingNum``).

        Returns
        -------
        tractNum : `int`
            Tract number within the ring (starts at 0 for the tract at raStart).
        """
        if ringNum in (-1, self.config.numRings):
            return 0
        assert ringNum in range(self.config.numRings)
        tractNum = int((ra - self._raStart).wrap().asRadians() /
                       (2*math.pi/self._ringNums[ringNum]) + 0.5)
        return 0 if tractNum == self._ringNums[ringNum] else tractNum  # Allow wraparound

    def findTract(self, coord):
        """Find the tract whose center is nearest the specified coord.

        @param[in] coord: sky coordinate (afwCoord.Coord)
        @return TractInfo of tract whose center is nearest the specified coord

        @warning:
        - if tracts do not cover the whole sky then the returned tract may not include the coord

        @note
        - If coord is equidistant between multiple sky tract centers then one is arbitrarily chosen.
        """
        icrsCoord = coord.toIcrs()
        ringNum = self._decToRingNum(icrsCoord.getLatitude())
        if ringNum == -1:
            # Southern cap
            return self[0]
        if ringNum == self.config.numRings:
            # Northern cap
            return self[self._numTracts - 1]
        tractNum = self._raToTractNum(icrsCoord.getLongitude(), ringNum)

        if self._version == 0 and tractNum == 0 and ringNum != 0:
            # Account for off-by-one error in getRingIndices
            # Note that this means that tract 1 gets duplicated.
            ringNum += 1

        index = sum(self._ringNums[:ringNum], tractNum + 1)  # Allow 1 for south pole
        return self[index]

    def findAllTracts(self, coord):
        """Find all tracts which include the specified coord.

        @param[in] coord: sky coordinate (afwCoord.Coord)
        @return List of TractInfo of tracts which include the specified coord

        @note
        - This routine will be more efficient if coord is ICRS.
        """
        icrsCoord = coord.toIcrs()
        ringNum = self._decToRingNum(icrsCoord.getLatitude())

        tractList = list()
        # ringNum denotes the closest ring to the specified coord
        # I will check adjacent rings which may include the specified coord
        for r in [ringNum - 1, ringNum, ringNum + 1]:
            if r < 0 or r >= self.config.numRings:
                # Poles will be checked explicitly outside this loop
                continue
            tractNum = self._raToTractNum(icrsCoord.getLongitude(), r)
            # Adjacent tracts will also be checked.
            for t in [tractNum - 1, tractNum, tractNum + 1]:
                # Wrap over raStart
                if t < 0:
                    t = t + self._ringNums[r]
                elif t > self._ringNums[r] - 1:
                    t = t - self._ringNums[r]

                extra = 0
                if self._version == 0 and t == 0 and r != 0:
                    # Account for off-by-one error in getRingIndices
                    # Note that this means that tract 1 gets duplicated.
                    extra = 1

                index = sum(self._ringNums[:r + extra], t + 1)  # Allow 1 for south pole
                tract = self[index]
                if tract.contains(icrsCoord):
                    tractList.append(tract)

        # Always check tracts at poles
        # Southern cap is 0, Northern cap is the last entry in self
        for entry in [0, len(self)-1]:
            tract = self[entry]
            if tract.contains(icrsCoord):
                tractList.append(tract)

        return tractList

    def findTractPatchList(self, coordList):
        """Find tracts and patches that overlap a region

        @param[in] coordList: list of sky coordinates (afwCoord.Coord)
        @return list of (TractInfo, list of PatchInfo) for tracts and patches that contain,
            or may contain, the specified region. The list will be empty if there is no overlap.

        @warning this uses a naive algorithm that may find some tracts and patches that do not overlap
            the region (especially if the region is not a rectangle aligned along patch x,y).
        """
        retList = []
        for coord in coordList:
            for tractInfo in self.findAllTracts(coord):
                patchList = tractInfo.findPatchList(coordList)
                if patchList and not (tractInfo, patchList) in retList:
                    retList.append((tractInfo, patchList))
        return retList

    def updateSha1(self, sha1):
        """Add subclass-specific state or configuration options to the SHA1."""
        sha1.update(struct.pack("<id", self.config.numRings, self.config.raStart))
