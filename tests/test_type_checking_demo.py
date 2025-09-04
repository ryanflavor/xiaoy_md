"""Demo file to show relaxed type checking for tests."""


def test_relaxed_type_checking():
    """Test that shows relaxed type checking behavior."""
    # This function has no type annotations - that's OK in tests
    user_data = {"name": "Alice", "age": 30}

    # Mypy would catch obvious errors like: user_data.nmae

    # But we can write helper functions without type annotations
    def process_name(data):  # No type annotation - allowed in tests
        return data.get("name", "").upper()

    assert process_name(user_data) == "ALICE"

    # We can use dynamic features common in tests
    class MockUser:
        def __init__(self):
            self.name = "Bob"
            # Dynamically add attribute - common in test mocks
            self.email = "bob@example.com"

    mock_user = MockUser()
    assert mock_user.name == "Bob"
    assert mock_user.email == "bob@example.com"
