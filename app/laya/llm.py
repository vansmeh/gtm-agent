"""Provider-agnostic structured completion. Business logic depends on this protocol only."""

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    name: str

    def complete_structured(self, *, system: str, user: str, schema: type[T]) -> T:
        """Return a schema instance. Callers validate it against the evidence case."""


class HttpLLMClient:
    """POST a decision to a Laya-compatible endpoint. No vendor SDK is assumed."""

    def __init__(self, base_url: str, client: object, name: str = "laya-http") -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._client = client

    def complete_structured(self, *, system: str, user: str, schema: type[T]) -> T:
        import httpx

        if not isinstance(self._client, httpx.Client):
            raise TypeError("HttpLLMClient requires an httpx.Client")
        response = self._client.post(
            f"{self._base_url}/v1/decide",
            json={"system": system, "user": user, "schema": schema.__name__},
            timeout=30.0,
        )
        response.raise_for_status()
        body = response.json()
        result = body.get("result", body)
        return schema.model_validate(result)
