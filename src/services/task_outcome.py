"""Explicit non-success outcomes for monitoring runs."""


class TaskSkipped(Exception):
    """No collection took place; not a successful zero-item search."""
