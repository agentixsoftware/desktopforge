"""Validation errors shared by recipes and read-only operation proposals."""


class RecipeError(ValueError):
    """Recipe data does not satisfy the supported schema."""
