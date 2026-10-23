# C-BIG MEG port notes

`cbig-meg` retains the C-BIG adaptation of upstream `3f95717` and replays
`3f95717..96aa6587` followed by the three MEG commits ending at `ba43f6a4`.
The former squashed MEG port is replaced by that stack. The final
`sync models with cbig` commit retains the C-BIG model adjustments.

## C-BIG compatibility

Existing C-BIG mappings remain, including `files.AcquisitionProtocolID`,
`session.CandID`, candidate GUID, project fields, MRI scan-type handling,
and event/HED mappings. Task events retain the previous MEG port's integer
EventSample and decimal ResponseTime mappings; fractional response times are
passed through without truncation.

The final commit excludes `candidate.DoD_precision`, `ConfigCategories`,
`ConfigSettings.CategoryID` and its relationship, and
`ConfigSettings.Multilingual`. Restore these mappings when C-BIG upgrades
to LORIS 30. C-BIG does not map `users.TOTPSecret`.

The replay includes the upstream head-shape models required by the BIDS
file-information commit, which were absent from the older C-BIG baseline.

## Database contracts to check before integration

The full upstream tarchive cleanup is accepted: use `StudyInstanceUID` and
nullable `InstitutionName`, and stop maintaining the legacy summary/tar
versions, acquisition metadata, transfer fields, and symbolic center name.
Review the archive model's nullability and defaults against the database.

The existing MEG/BIDS contracts remain: `bids_dataset`, `bids_file`, BIDS
links on imaging/physiological/event/head-shape files, MEG head-shape tables,
`meegqc_file` and `meegqc_file_acquisition`, and the server's permission,
module and login-history contracts. Coordinate systems additionally require
nullable `BidsFileID` referencing `bids_file.ID` with `ON DELETE SET NULL`.
Review the coordinate-system electrode/point foreign keys and deletion rules.

Server configuration still requires `JWTKey`, visualization settings, and
module/permission installation data. This replay does not migrate a database.

## Validation boundary

Unit tests use in-memory SQLite. Live import/server integration requires a
migrated C-BIG database and runtime. The incoming Raisinbread fixtures target
the upstream schema, including `session.CandidateID`; they need C-BIG-specific
data before running against the C-BIG schema.
