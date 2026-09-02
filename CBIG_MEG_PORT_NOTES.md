# C-BIG MEG port notes

`cbig-meg` ports the Python feature delta from `meg_import` onto
`cbig-sync-q1k`. The `loris_tus_server` experiment is deliberately excluded.

The port uses the `meg_import` implementation for BIDS importing, MEG,
MEEGqc, the electrophysiology visualizer, the Python server, and permissions.
Existing C-BIG overrides are retained where they describe the fork's current
schema or behavior, notably:

- `files.AcquisitionProtocolID` in place of `files.MriScanTypeID`;
- the C-BIG MRI scan-type handling in the NIfTI insertion pipeline;
- C-BIG event/HED field mappings;
- C-BIG candidate, project, session, and validation overrides.

## Transitive Python dependencies

Some code used by `meg_import` already existed in its newer upstream baseline
and was therefore not present in the feature diff. The following dependencies
were copied from the final `meg_import` tree as part of this port:

- the closable `Env` implementation and optional log-file handling;
- BIDS path helpers;
- `loris_utils` path and dictionary-sorting helpers;
- the MEG CTF head-shape point model.

## Database work required before integration testing

The Python models are authoritative for the later database patch. At minimum,
the C-BIG schema must be checked or updated for the following contracts:

- new `bids_dataset` and `bids_file` tables, including the dataset/path unique
  constraint and BLAKE2b/source/derivative metadata;
- nullable `BidsInfoID` foreign keys on `files`, `physiological_file`, and
  `physiological_event_file`;
- new `meg_ctf_head_shape_file` and `meg_ctf_head_shape_point` tables and the
  nullable `physiological_file.HeadShapeFileID` foreign key;
- new `meegqc_file` table;
- `users.TOTPSecret`;
- `modules`, `permissions`, `permissions_category`, `user_perm_rel`, and
  `user_login_history` tables/columns expected by the server and permission
  models;
- a `JWTKey` configuration entry for bearer-token validation;
- configuration used by electrophysiology visualization, particularly
  `useEEGBrowserVisualizationComponents` and the optional `EEGChunksPath`;
- module/permission installation data for the ephys visualizer and MEEGqc
  server modules.

The database patch should retain the C-BIG `AcquisitionProtocolID` mapping;
the port intentionally does not change it to `MriScanTypeID`.

## Validation boundary

Only database-independent checks are expected in the current environment.
Integration imports and live server checks must wait for the database patch
and a C-BIG runtime environment.
