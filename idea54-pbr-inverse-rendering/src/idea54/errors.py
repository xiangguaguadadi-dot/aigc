class Idea54Error(RuntimeError):
    """Stable, user-facing runtime error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")
