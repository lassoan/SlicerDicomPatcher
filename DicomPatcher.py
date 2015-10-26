import os
import unittest
from __main__ import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging

#
# DicomPatcher
#

class DicomPatcher(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "DICOM patcher"
    self.parent.categories = ["Informatics"]
    self.parent.dependencies = ["DICOM"]
    self.parent.contributors = ["Andras Lasso (PerkLab)"]
    self.parent.helpText = """Fix invalid DICOM files by generating missing fields. It is assumed that all files in the same directory belong to the same image series (e.g., slices of the same volume)."""
    self.parent.acknowledgementText = """ """

#
# DicomPatcherWidget
#

class DicomPatcherWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    # Instantiate and connect widgets ...

    #
    # Parameters Area
    #
    parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    parametersCollapsibleButton.text = "Parameters"
    self.layout.addWidget(parametersCollapsibleButton)

    # Layout within the dummy collapsible button
    parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

    self.inputDirSelector = ctk.ctkPathLineEdit()
    self.inputDirSelector.filters = ctk.ctkPathLineEdit.Dirs
    self.inputDirSelector.settingKey = 'DicomPatcherInputDir'
    parametersFormLayout.addRow("Input DICOM directory:", self.inputDirSelector)

    self.outputDirSelector = ctk.ctkPathLineEdit()
    self.outputDirSelector.filters = ctk.ctkPathLineEdit.Dirs
    self.outputDirSelector.settingKey = 'DicomPatcherOutputDir'
    parametersFormLayout.addRow("Output DICOM directory:", self.outputDirSelector)

    self.generateMissingIdsCheckBox = qt.QCheckBox()
    self.generateMissingIdsCheckBox.checked = True
    self.generateMissingIdsCheckBox.setToolTip("If checked, then missing patient, study, series IDs are generated. It is assumed that all files in a directory belong to the same series. Fixes error caused by too aggressive anonymization or incorrect DICOM image converters.")
    parametersFormLayout.addRow("Generate missing IDs", self.generateMissingIdsCheckBox)
    
    self.generateImagePositionFromSliceThicknessCheckBox = qt.QCheckBox()
    self.generateImagePositionFromSliceThicknessCheckBox.checked = True
    self.generateImagePositionFromSliceThicknessCheckBox.setToolTip("If checked, then image position sequence is generated for multi-frame files that only have SliceThickness field. Fixes error in Dolphin 3D CBCT scanners.")
    parametersFormLayout.addRow("Generate slice position for multi-frame volumes", self.generateImagePositionFromSliceThicknessCheckBox)
    
    self.anonymizeDicomCheckBox = qt.QCheckBox()
    self.anonymizeDicomCheckBox.checked = False
    self.anonymizeDicomCheckBox.setToolTip("If checked, then some patient identifiable information will be removed from the patched DICOM files. There are many fields that can identify a patient, this function does not remove all of them.")
    parametersFormLayout.addRow("Anonymize DICOM files", self.anonymizeDicomCheckBox)

    #
    # Patch Button
    #
    self.patchButton = qt.QPushButton("Patch")
    self.patchButton.toolTip = "Fix and optionally anonymize DICOM files"
    parametersFormLayout.addRow(self.patchButton)

    # connections
    self.patchButton.connect('clicked(bool)', self.onPatchButton)
    
    self.statusLabel = qt.QPlainTextEdit()
    self.statusLabel.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
    parametersFormLayout.addRow(self.statusLabel)

    # Add vertical spacer
    self.layout.addStretch(1)
    
    self.logic = DicomPatcherLogic()
    self.logic.logCallback = self.addLog

  def cleanup(self):
    pass

  def onPatchButton(self):
    slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
    try:
      self.inputDirSelector.addCurrentPathToHistory()
      self.outputDirSelector.addCurrentPathToHistory()
      self.statusLabel.plainText = ''
      self.logic.patchDicomDir(self.inputDirSelector.currentPath, self.outputDirSelector.currentPath, generateMissingIds = self.generateMissingIdsCheckBox.checked, generateImagePositionFromSliceThickness = self.generateImagePositionFromSliceThicknessCheckBox.checked, anonymize = self.anonymizeDicomCheckBox.checked)
    except Exception as e:
      self.addLog("Unexpected error: {0}".format(e.message))
      import traceback
      traceback.print_exc()
    slicer.app.restoreOverrideCursor();
  
  def addLog(self, text):
    """Append text to log window
    """
    self.statusLabel.appendPlainText(text)
    slicer.app.processEvents() # force update

#
# DicomPatcherLogic
#

class DicomPatcherLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)
    self.logCallback = None
    
  def addLog(self, text):
    logging.info(text)
    if self.logCallback:
      self.logCallback(text)

  def patchDicomDir(self, inputDirPath, outputDirPath, generateMissingIds = True, generateImagePositionFromSliceThickness = True, anonymize = False):
    """
    Since CTK (rightly) requires certain basic information [1] before it can import
    data files that purport to be dicom, this code patches the files in a directory
    with some needed fields.  Apparently it is possible to export files from the
    Philips PMS QLAB system with these fields missing.

    Calling this function with a directory path will make a patched copy of each file.
    Importing the old files to CTK should still fail, but the new ones should work.

    The directory is assumed to have a set of instances that are all from the
    same study of the same patient.  Also that each instance (file) is an
    independent (multiframe) series.

    [1] https://github.com/commontk/CTK/blob/16aa09540dcb59c6eafde4d9a88dfee1f0948edc/Libs/DICOM/Core/ctkDICOMDatabase.cpp#L1283-L1287
    """

    import dicom

    if not outputDirPath:
      outputDirPath = inputDirPath
    
    self.addLog('DICOM patching started...')
    logging.debug('DICOM patch input directory: '+inputDirPath)
    logging.debug('DICOM patch output directory: '+outputDirPath)

    patientIDToRandomIDMap = {}
    studyUIDToRandomUIDMap = {}
    seriesUIDToRandomUIDMap = {}
    numberOfSeriesInStudyMap = {}

    # All files without a patient ID will be assigned to the same patient
    randomPatientID = dicom.UID.generate_uid(None)
    
    requiredTags = ['PatientName', 'PatientID', 'StudyInstanceUID', 'SeriesInstanceUID', 'SeriesNumber']
    for root, subFolders, files in os.walk(inputDirPath):
    
      # Assume that all files in a directory belongs to the same study
      randomStudyUID = dicom.UID.generate_uid(None)

      # Assume that all files in a directory belongs to the same series
      randomSeriesInstanceUID = dicom.UID.generate_uid(None)
      
      currentSubDir = os.path.relpath(root, inputDirPath)
      rootOutput = os.path.join(outputDirPath, currentSubDir)
      
      for file in files:
        filePath = os.path.join(root,file)
        self.addLog('Examining %s...' % os.path.join(currentSubDir,file))
        try:
          ds = dicom.read_file(filePath)
        except (IOError, dicom.filereader.InvalidDicomError):
          self.addLog('  Not DICOM file. Skipped.')
          continue

        self.addLog('  Patching...')

        ######################################################
        # Add missing IDs
        if generateMissingIds:
        
          for tag in requiredTags:
            if not hasattr(ds,tag):
              setattr(ds,tag,'')
              
          # Generate a new SOPInstanceUID to avoid different files having the same SOPInstanceUID
          ds.SOPInstanceUID = dicom.UID.generate_uid(None)
              
          if ds.PatientName == '':
            ds.PatientName = "Unspecified Patient"
          if ds.PatientID == '':
            ds.PatientID = randomPatientID
          if ds.StudyInstanceUID == '':
            ds.StudyInstanceUID = randomStudyUID
          if ds.SeriesInstanceUID == '':
            #ds.SeriesInstanceUID = dicom.UID.generate_uid(None) # this line has to be used if each file is a separate series
            ds.SeriesInstanceUID = randomSeriesInstanceUID
            
          # Generate series number to make it easier to identify a sequence within a study
          if ds.SeriesNumber == '':
            if ds.StudyInstanceUID not in numberOfSeriesInStudyMap:
              numberOfSeriesInStudyMap[ds.StudyInstanceUID] = 0
            numberOfSeriesInStudyMap[ds.StudyInstanceUID] = numberOfSeriesInStudyMap[ds.StudyInstanceUID] + 1
            ds.SeriesNumber = numberOfSeriesInStudyMap[ds.StudyInstanceUID]

        ######################################################
        # Add missing slice spacing info to multiframe files
        numberOfFrames = ds.NumberOfFrames if hasattr(ds,'NumberOfFrames') else 1
        if generateImagePositionFromSliceThickness and numberOfFrames>1:
          # Multi-frame sequence, we may need to add slice positions
          
          # Error in Dolphin 3D CBCT scanners, they store multiple frames but they keep using CTImageStorage as storage class
          if ds.SOPClassUID == '1.2.840.10008.5.1.4.1.1.2': # Computed Tomography Image IOD
            ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.2.1' # Enhanced CT Image IOD

          sliceStartPosition = ds.ImagePositionPatient if hasattr(ds,'ImagePositionPatient') else [0,0,0]
          sliceAxes = ds.ImageOrientationPatient if hasattr(ds,'ImagePositionPatient') else [1,0,0,0,1,0]
          x = sliceAxes[:3]
          y = sliceAxes[3:]
          z = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]] # cross(x,y)
          sliceSpacing = ds.SliceThickness if hasattr(ds,'SliceThickness') else 1.0
          pixelSpacing = ds.PixelSpacing if hasattr(ds,'PixelSpacing') else [1.0, 1.0]
            
          if not (dicom.tag.Tag(0x5200,0x9229) in ds):

            # (5200,9229) SQ (Sequence with undefined length #=1)     # u/l, 1 SharedFunctionalGroupsSequence
            #   (0020,9116) SQ (Sequence with undefined length #=1)     # u/l, 1 PlaneOrientationSequence
            #       (0020,0037) DS [1.00000\0.00000\0.00000\0.00000\1.00000\0.00000] #  48, 6 ImageOrientationPatient
            #   (0028,9110) SQ (Sequence with undefined length #=1)     # u/l, 1 PixelMeasuresSequence
            #       (0018,0050) DS [3.00000]                                #   8, 1 SliceThickness
            #       (0028,0030) DS [0.597656\0.597656]                      #  18, 2 PixelSpacing

            planeOrientationDataSet = dicom.dataset.Dataset()
            planeOrientationDataSet.ImageOrientationPatient = sliceAxes
            planeOrientationSequence = dicom.sequence.Sequence()
            planeOrientationSequence.insert(dicom.tag.Tag(0x0020,0x9116),planeOrientationDataSet)

            pixelMeasuresDataSet = dicom.dataset.Dataset()
            pixelMeasuresDataSet.SliceThickness = sliceSpacing
            pixelMeasuresDataSet.PixelSpacing = pixelSpacing
            pixelMeasuresSequence = dicom.sequence.Sequence()
            pixelMeasuresSequence.insert(dicom.tag.Tag(0x0028,0x9110),pixelMeasuresDataSet)

            sharedFunctionalGroupsDataSet = dicom.dataset.Dataset()
            sharedFunctionalGroupsDataSet.PlaneOrientationSequence = planeOrientationSequence
            sharedFunctionalGroupsDataSet.PixelMeasuresSequence = pixelMeasuresSequence
            sharedFunctionalGroupsSequence = dicom.sequence.Sequence()
            sharedFunctionalGroupsSequence.insert(dicom.tag.Tag(0x5200,0x9229),sharedFunctionalGroupsDataSet)
            ds.SharedFunctionalGroupsSequence = sharedFunctionalGroupsSequence

          if not (dicom.tag.Tag(0x5200,0x9230) in ds):

            #(5200,9230) SQ (Sequence with undefined length #=54)    # u/l, 1 PerFrameFunctionalGroupsSequence
            #  (0020,9113) SQ (Sequence with undefined length #=1)     # u/l, 1 PlanePositionSequence
            #    (0020,0032) DS [-94.7012\-312.701\-806.500]             #  26, 3 ImagePositionPatient
            #  (0020,9113) SQ (Sequence with undefined length #=1)     # u/l, 1 PlanePositionSequence
            #    (0020,0032) DS [-94.7012\-312.701\-809.500]             #  26, 3 ImagePositionPatient
            #  ...

            perFrameFunctionalGroupsSequence = dicom.sequence.Sequence()

            for frameIndex in range(numberOfFrames):
              planePositionDataSet = dicom.dataset.Dataset()
              slicePosition = [sliceStartPosition[0]+frameIndex*z[0]*sliceSpacing, sliceStartPosition[1]+frameIndex*z[1]*sliceSpacing, sliceStartPosition[2]+frameIndex*z[2]*sliceSpacing]
              planePositionDataSet.ImagePositionPatient = slicePosition
              planePositionSequence = dicom.sequence.Sequence()
              planePositionSequence.insert(dicom.tag.Tag(0x0020,0x9113),planePositionDataSet)
              perFrameFunctionalGroupsDataSet = dicom.dataset.Dataset()
              perFrameFunctionalGroupsDataSet.PlanePositionSequence = planePositionSequence
              perFrameFunctionalGroupsSequence.insert(dicom.tag.Tag(0x5200,0x9230),perFrameFunctionalGroupsDataSet)

            ds.PerFrameFunctionalGroupsSequence = perFrameFunctionalGroupsSequence
            
        ######################################################
        # Anonymize
        if anonymize:

          self.addLog('  Anonymizing...')

          ds.StudyDate = ''
          ds.StudyTime = ''
          ds.ContentDate = ''
          ds.ContentTime = ''
          ds.AccessionNumber = ''
          ds.ReferringPhysiciansName = ''
          ds.PatientsBirthDate = ''
          ds.PatientsSex = ''
          ds.StudyID = ''
          ds.PatientName = "Unspecified Patient"

          # replace ids with random values - re-use if we have seen them before
          if ds.PatientID not in patientIDToRandomIDMap:  
            patientIDToRandomIDMap[ds.PatientID] = dicom.UID.generate_uid(None)
          ds.PatientID = patientIDToRandomIDMap[ds.PatientID]
          if ds.StudyInstanceUID not in studyUIDToRandomUIDMap:  
            studyUIDToRandomUIDMap[ds.StudyInstanceUID] = dicom.UID.generate_uid(None)
          ds.StudyInstanceUID = studyUIDToRandomUIDMap[ds.StudyInstanceUID]  
          if ds.SeriesInstanceUID not in studyUIDToRandomUIDMap:
            seriesUIDToRandomUIDMap[ds.SeriesInstanceUID] = dicom.UID.generate_uid(None)
          ds.SeriesInstanceUID = seriesUIDToRandomUIDMap[ds.SeriesInstanceUID]

        ######################################################
        # Write
        if inputDirPath==outputDirPath:
          (name, ext) = os.path.splitext(filePath)
          patchedFilePath = name + ('-anon' if anonymize else '') + '-patched' + ext
        else:
          patchedFilePath = os.path.abspath(os.path.join(rootOutput,file))
          if not os.path.exists(rootOutput):
            os.makedirs(rootOutput)

        self.addLog('  Writing DICOM...')
        dicom.write_file(patchedFilePath, ds)
        self.addLog('  Created DICOM file: %s' % patchedFilePath)

    self.addLog('DICOM patching completed.')


class DicomPatcherTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_DicomPatcher1()

  def test_DicomPatcher1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests should exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    self.delayDisplay("No tests are implemented")
