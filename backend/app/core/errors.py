from fastapi import HTTPException


class APIError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
        details: list[dict[str, str]] | None = None,
    ) -> None:
        self.code = code
        self.details = details or []
        super().__init__(status_code=status_code, detail=message, headers=headers)
