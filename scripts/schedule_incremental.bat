@echo off
REM Schedule helper: runs incremental ingestion for configured areas
REM Use Task Scheduler to call this file nightly.

REM Ensure poetry environment activated or use plain python if available
poetry run python scripts\run_incremental_all.py
