# LORIS DICOM to BIDS converter

The LORIS DICOM to BIDS converter is a pipeline used to convert a LORIS DICOM archive to the BIDS format and insert the result into LORIS.

## Installation

This package is installed by default with LORIS Python.

## Pipeline

The LORIS DICOM to BIDS converter proceeds in several steps:
1. Unwrap the DICOM study stored in a LORIS DICOM archive and validate its information (checksum, subject/session/scanner information).
2. Convert each DICOM series of the DICOM study to NIfTI using [dcm2niix](https://github.com/rordenlab/dcm2niix).
3. Classify the generated files according to the relevant LORIS MRI protocol configuration, and register them in the LORIS `assembly_bids` BIDS dataset or register them as an MRI protocol violation.
4. (optional) Push the converted files to AWS S3 storage and update their information in the LORIS database.

## Scripts

The LORIS DICOM to BIDS converter is composed of several CLI scripts:
- `convert-dicom-archive-to-bids`: Run the full pipeline on a DICOM archive (steps 1 to 3 above).
- `validate-dicom-archive`: Validate the DICOM archive (step 1 above).
- `insert-nifti`: Classify and insert a NIfTI file and its associated files in the LORIS BIDS dataset (step 3 above).
- `push-imaging-files-to-s3`: Push the converted files to AWS S3 (step 4 above).
