# ----------------------------------------------------------------------
# Numenta Platform for Intelligent Computing (NuPIC)
# Copyright (C) 2016, Numenta, Inc.  Unless you have an agreement
# with Numenta, Inc., for a separate license for this software code, the
# following terms and conditions apply:
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU Affero Public License for more details.
#
# You should have received a copy of the GNU Affero Public License
# along with this program.  If not, see http://www.gnu.org/licenses.
#
# http://numenta.org/licenses/
# ----------------------------------------------------------------------

import numpy

from nupic.bindings.math import (SM32 as SparseMatrix,
                                 SM_01_32_32 as SparseBinaryMatrix,
                                 GetNTAReal)
from nupic.research.connections import Connections

from htmresearch.algorithms.extended_temporal_memory import (
  ExtendedTemporalMemory
)

realDType = GetNTAReal()
uintType = "uint32"



class ColumnPooler(ExtendedTemporalMemory):
  """
  This class constitutes a temporary implementation for a cross-column pooler.
  The implementation goal of this class is to prove basic properties before
  creating a cleaner implementation.
  """

  def __init__(self,
               inputWidth,
               numActiveColumnsPerInhArea=40,
               synPermProximalInc=0.1,
               synPermProximalDec=0.001,
               initialProximalPermanence=0.6,
               distalActivationThreshold=13,
               distalMinThreshold=13,
               maxSynapsesPerDistalSegment=511,
               numNeighboringColumns=0,
               lateralInputWidth=None,
               **kwargs):
    """
    Please see ExtendedTemporalMemory for descriptions of common constructor
    parameters.

    Parameters:
    ----------------------------
    @param  inputWidth (int)
            The number of proximal inputs into this layer

    @param  numActiveColumnsPerInhArea (int)
            Number of active cells

    @param  synPermProximalInc (float)
            Permanence increment for proximal synapses

    @param  synPermProximalDec (float)
            Permanence decrement for proximal synapses

    @param  initialProximalPermanence (float)
            Initial permanence value for proximal segments
    """

    # Override: we only support one cell per column for now
    kwargs['cellsPerColumn'] = 1
    super(ColumnPooler, self).__init__(**kwargs)

    self.inputWidth = inputWidth
    self.numActiveColumnsPerInhArea = numActiveColumnsPerInhArea
    self.synPermProximalInc = synPermProximalInc
    self.synPermProximalDec = synPermProximalDec
    self.initialProximalPermanence = initialProximalPermanence
    self.previousOverlaps = None

    # These sparse matrices will hold the synapses for each proximal segment.
    #
    # proximalPermanences - SparseMatrix with permanence values
    # proximalConnections - SparseBinaryMatrix of connected synapses


    self.proximalPermanences = SparseMatrix(self.numberOfColumns(),
                                               inputWidth)
    self.proximalConnections = SparseBinaryMatrix(inputWidth)
    self.proximalConnections.resize(self.numberOfColumns(), inputWidth)

    # if no specified input width, assume that it is from similar Poolers
    if lateralInputWidth is None:
      lateralInputWidth = self.numberOfCells()
    self.lateralInputWidth = lateralInputWidth

    self.numNeighboringColumns = numNeighboringColumns
    self.distalConnections = []
    self.activeDistalSegments = []
    # create one Connection object per neighboring Column
    for _ in xrange(numNeighboringColumns):
      self.distalConnections.append(
        Connections(self.numberOfCells(), 1, maxSynapsesPerDistalSegment)
      )
      self.activeDistalSegments.append(set())

    self.distalActivationThreshold = distalActivationThreshold
    self.distalMinThreshold = distalMinThreshold

  def compute(self,
              feedforwardInput=None,
              activeExternalCells=None,
              activeApicalCells=None,
              formInternalConnections=True,
              learn=True):
    """

    Parameters:
    ----------------------------
    @param  feedforwardInput     (set)
            Indices of active input bits

    @param  activeExternalCells  (set)
            Indices of active cells that will form connections to distal
            segments.

    @param  activeApicalCells (set)
            Indices of active cells that will form connections to apical
            segments.

    @param  formInternalConnections (bool)
            If True, cells will form

    @param learn                If True, we are learning a new object

    """
    if activeExternalCells is None:
      activeExternalCells = []

    if activeApicalCells is None:
      activeApicalCells = set()

    if learn:
      self._computeLearningMode(feedforwardInput=feedforwardInput,
                               lateralInput=activeExternalCells)

    else:
      self._computeInferenceMode(feedforwardInput=feedforwardInput,
                                 lateralInput=activeExternalCells)


  def _computeLearningMode(self, feedforwardInput, lateralInput):
    """
    Learning mode: we are learning a new object. If there is no prior
    activity, we randomly activate 2% of cells and create connections to
    incoming input. If there was prior activity, we maintain it.

    These cells will represent the object and learn distal connections to
    lateral cortical columns.

    Parameters:
    ----------------------------
    @param  feedforwardInput (set)
            Indices of active input bits

    @param  lateralInput (list of lists)
            A list of list of active cells from neighboring columns.
            len(lateralInput) == number of connected neighboring cortical
            columns.

    """
    if len(lateralInput) > 0 and \
       len(lateralInput) < self.numNeighboringColumns:
      raise ValueError("Incorrect dimension for lateral input!")

    # If there are no previously active cells, select random subset of cells
    if len(self.activeCells) == 0:
      self.activeCells = set(self._random.shuffle(
            numpy.array(range(self.numberOfCells()),
                        dtype="uint32"))[0:self.numActiveColumnsPerInhArea])

    # else we maintain previous activity, nothing to do.

    # Incorporate distal segment activity and update list of active cells
    self.activeCells = self._winnersBasedOnLateralActivity(
      self.activeCells, lateralInput, self.distalMinThreshold
    )

    # Those cells that remain active will learn on their proximal and distal
    # dendrites as long as there is some input.  If there are no
    # cells active, no learning happens.
    if len(self.activeCells) > 0:

      # Learn on proximal dendrite if appropriate
      if len(feedforwardInput) > 0:
        self._learnProximal(feedforwardInput, self.activeCells,
                            self.maxNewSynapseCount, self.proximalPermanences,
                            self.proximalConnections,
                            self.initialProximalPermanence,
                            self.synPermProximalInc, self.synPermProximalDec,
                            self.connectedPermanence)

      # Learn on distal dendrites if appropriate
      if len(lateralInput) > 0:
        self._learnDistal(lateralInput, self.activeCells)


  def _computeInferenceMode(self, feedforwardInput, lateralInput):
    """
    Inference mode: if there is some feedforward activity, perform
    spatial pooling on it to recognize previously known objects. If there
    is no feedforward activity, maintain previous activity.

    Parameters:
    ----------------------------
    @param  feedforwardInput (set)
            Indices of active input bits

    @param  lateralInput (list of lists)
            A list of list of active cells from neighboring columns.
            len(lateralInput) == number of connected neighboring cortical
            columns.

    """
    # Figure out which cells are active due to feedforward proximal inputs
    inputVector = numpy.zeros(self.numberOfInputs(), dtype=realDType)
    inputVector[list(feedforwardInput)] = 1
    overlaps = numpy.zeros(self.numberOfColumns(), dtype=realDType)
    self.proximalConnections.rightVecSumAtNZ_fast(inputVector.astype(realDType),
                                                 overlaps)
    overlaps[overlaps < self.minThreshold] = 0
    bottomUpActivity =  set(overlaps.nonzero()[0])

    # In order to form unions, we keep all cells that are over threshold
    self.activeCells = self._winnersBasedOnLateralActivity(
      bottomUpActivity,
      lateralInput,
      self.distalMinThreshold
    )


  def numberOfInputs(self):
    """
    Returns the number of inputs into this layer
    """
    return self.inputWidth


  def numberOfConnectedSynapses(self, cells):
    """
    Returns the number of connected synapses on these cells.

    Parameters:
    ----------------------------
    @param  cells (set or list)
            Indices of the cells
    """
    n = 0
    for cell in cells:
      n += self.proximalConnections.nNonZerosOnRow(cell)
    return n


  def numberOfSynapses(self, cells):
    """
    Returns the number of synapses with permanence>0 on these cells.

    Parameters:
    ----------------------------
    @param  cells (set or list)
            Indices of the cells
    """
    n = 0
    for cell in cells:
      n += self.proximalPermanences.nNonZerosOnRow(cell)
    return n


  def _learnProximal(self,
             activeInputs, activeCells, maxNewSynapseCount, proximalPermanences,
             proximalConnections, initialPermanence, synPermProximalInc,
             synPermProximalDec, connectedPermanence):
    """
    Learn on proximal dendrites of active cells.  Updates proximalPermanences
    """
    for cell in activeCells:
      cellPermanencesDense = proximalPermanences.getRow(cell)
      cellNonZeroIndices, _ = proximalPermanences.rowNonZeros(cell)
      cellNonZeroIndices = list(cellNonZeroIndices)

      # Get new and existing connections for this segment
      newInputs, existingInputs = self._pickProximalInputsToLearnOn(
        maxNewSynapseCount, activeInputs, cellNonZeroIndices
      )

      # Adjust existing connections appropriately
      # First we decrement all existing permanences
      if len(cellNonZeroIndices) > 0:
        cellPermanencesDense[cellNonZeroIndices] -= synPermProximalDec

      # Then we add inc + dec to existing active synapses
      if len(existingInputs) > 0:
        cellPermanencesDense[existingInputs] += synPermProximalInc + synPermProximalDec

      # Add new connections
      if len(newInputs) > 0:
        cellPermanencesDense[newInputs] += initialPermanence

      # Update proximalPermanences and proximalConnections
      proximalPermanences.setRowFromDense(cell, cellPermanencesDense)
      newConnected = numpy.where(cellPermanencesDense >= connectedPermanence)[0]
      proximalConnections.replaceSparseRow(cell, newConnected)

      cellNonZeroIndices, _ = proximalPermanences.rowNonZeros(cell)


  def _winnersBasedOnLateralActivity(self,
                                     activeCells,
                                     lateralInput,
                                     minThreshold):
    """
    Incorporate effect of lateral activity, if any, and update the set of
    winners.

    UNIMPLEMENTED

    @return (set) list of new winner cell indices
    """
    if len(lateralInput) == 0 or \
       sum([len(latInput) for latInput in lateralInput]) == 0:
      # if there is not enough bottom-up activity, persist
      if len(activeCells) == 0:
        return self.activeCells
      else:
        return activeCells

    lateralActivity = {}
    maxNumberOfDistalSegments = 0
    # winner cells will be computed in one pass
    winnerCells = []

    for cell in activeCells:
      lateralActivity[cell] = self._numberOfActiveDistalSegments(
        cell,
        lateralInput,
        self.connectedPermanence,
        self.distalActivationThreshold,
      )

      # keep track of maximum number of active distal segments
      if lateralActivity[cell] > maxNumberOfDistalSegments:
        maxNumberOfDistalSegments = lateralActivity[cell]
        winnerCells = []

      if lateralActivity[cell] == maxNumberOfDistalSegments:
        winnerCells.append(cell)

    return set(winnerCells)


  def _numberOfActiveDistalSegments(self,
                                    cell,
                                    lateralInput,
                                    connectedPermanence,
                                    activationThreshold):
    """
    Counts the number of active segments for the given cell.

    Parameters:
    ----------------------------
    @param   cell                  (int)
             Cell index

    @param   lateralInput          (list(list))
             List of lateral activations

    @param   connectedPermanence   (float)
             Permanence threshold for a synapse to be considered active

    @param   activationThreshold   (int)
             Number of synapses needed for a segment to be considered active

    """
    numActiveSegments = 0

    for neighbor in xrange(self.numNeighboringColumns):

      # for each set of connections, check if segment is active
      connections = self.distalConnections[neighbor]
      segments = connections.segmentsForCell(cell)
      if len(segments) > 0:
        segment = list(segments)[0]
      else:
        continue

      numActiveSynapsesForSegment = 0
      for synapse in connections.synapsesForSegment(segment):
        synapseData = connections.dataForSynapse(synapse)
        if synapseData.presynapticCell not in lateralInput[neighbor]:
          continue

        if synapseData.permanence >= connectedPermanence:
          numActiveSynapsesForSegment += 1
          if numActiveSynapsesForSegment >= activationThreshold:
            # add active segment
            self.activeDistalSegments[neighbor].add(segment)
            # increment counter
            numActiveSegments += 1
            break

    return numActiveSegments


  def _pickProximalInputsToLearnOn(self, newSynapseCount, activeInputs,
                                  cellNonZeros):
    """
    Pick inputs to form proximal connections to. We just randomly subsample
    from activeInputs, regardless of whether they are already connected.

    We return a list of up to newSynapseCount input indices from activeInputs
    that are valid new connections for this cell. We also return a list
    containing all inputs in activeInputs that are already connected to this
    cell.

    Parameters:
    ----------------------------
    @param newSynapseCount  (int)        Number of inputs to pick
    @param cell             (int)        Cell index
    @param activeInputs     (set)        Indices of active inputs
    @param proximalPermanences (sparse)  The matrix of proximal connections

    @return (list, list) Indices of new inputs to connect to, inputs already
                         connected
    """
    candidates = []
    alreadyConnected = []

    # Collect inputs that already have synapses and list of new candidate inputs
    for inputIdx in activeInputs:
      if inputIdx in cellNonZeros:
        alreadyConnected += [inputIdx]
      else:
        candidates += [inputIdx]

    # Select min(newSynapseCount, len(candidates)) new inputs to connect to
    if newSynapseCount >= len(candidates):
      return candidates, alreadyConnected

    else:
      # Pick newSynapseCount cells randomly
      # TODO: we could maybe implement this more efficiently with shuffle.
      inputs = []
      for _ in range(newSynapseCount):
        i = self._random.getUInt32(len(candidates))
        inputs += [candidates[i]]
        candidates.remove(candidates[i])

      # print "number of new candidates:",len(inputs)

      return inputs, alreadyConnected


  def _learnDistal(self, lateralInput, activeCells):
    pass

