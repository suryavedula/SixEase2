"""Workbook loaders package (EPIC-02).

Each loader is a standalone async function that can be called from the admin
seed endpoint or from a one-shot management script. All loaders are idempotent
(safe to run multiple times) and commit their own transaction.
"""
