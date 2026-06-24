"""Offline overnight-batch analysis.

The factory edge box records ~25 cameras all day and ships the files to the
office GPU box. This package crunches those recordings through the same
``CameraPipeline`` the live path uses (headless, no display/broadcast), stamps
the resulting ``metric_samples`` with each recording's REAL wall-clock start
time (parsed from the NVR filename), and rolls a whole factory-day up into a
PDF day summary.

Modules:
  runner   — process one recording file end-to-end (the engine).
  ingest   — NVR filename parsing + camera resolution + processed-file ledger.
"""
