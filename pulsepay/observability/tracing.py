from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

_request_id_ctx_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(id: str) -> None:
	_request_id_ctx_var.set(id)


def get_request_id() -> str | None:
	return _request_id_ctx_var.get()


@contextmanager
def new_request_context() -> Generator[str, None, None]:
	request_id = str(uuid4())
	token = _request_id_ctx_var.set(request_id)
	try:
		yield request_id
	finally:
		_request_id_ctx_var.reset(token)
