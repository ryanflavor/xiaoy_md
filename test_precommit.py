"""Test file to demonstrate pre-commit behavior."""


def broken_function():
    """This function has an obvious error."""
    text = "hello"
    text.append(" world")  # Error: str has no append method
    return text
