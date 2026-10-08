---
type: Guide
title: Testing Guide
description: pytest structure, fixtures, and testing patterns for this repo.
tags: [testing, pytest, conventions]
---

# Testing Guide

Testing patterns for Python (pytest).

## Python Testing (pytest)

### Basic Test Structure
```python
import pytest

# Function-based tests (preferred over class-based)
def test_addition():
    assert 1 + 1 == 2

def test_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        1 / 0

# Parametrized tests
@pytest.mark.parametrize("input,expected", [
    ("hello", 5),
    ("", 0),
    ("world", 5),
])
def test_string_length(input: str, expected: int):
    assert len(input) == expected
```

### Async Tests
```python
import pytest
from httpx import AsyncClient

@pytest.mark.anyio
async def test_async_endpoint(client: AsyncClient):
    response = await client.get("/api/items")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

### Fixtures
```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from collections.abc import AsyncGenerator

@pytest.fixture
def sample_user() -> User:
    return User(name="Test", email="test@example.com")

@pytest.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(engine) as session:
        yield session
        await session.rollback()

@pytest.fixture(scope="module")
def client(app) -> TestClient:
    return TestClient(app)
```

### Mocking
```python
from unittest.mock import AsyncMock, MagicMock, patch

def test_with_mock():
    with patch("module.external_api") as mock_api:
        mock_api.return_value = {"status": "ok"}
        result = function_that_calls_api()
        assert result["status"] == "ok"
        mock_api.assert_called_once()

@pytest.fixture
def mock_service():
    service = MagicMock(spec=MyService)
    service.fetch_data = AsyncMock(return_value=[])
    return service
```

### HTTP Testing with Litestar
```python
from litestar.testing import TestClient

def test_get_items(client: TestClient):
    response = client.get("/items")
    assert response.status_code == 200

def test_create_item(client: TestClient):
    response = client.post("/items", json={"name": "Test"})
    assert response.status_code == 201
    assert response.json()["name"] == "Test"
```

### Coverage
```bash
# Run with coverage
pytest --cov=src --cov-report=html

# Fail if coverage below threshold
pytest --cov=src --cov-fail-under=90
```

---

## Best Practices

- Use function-based tests (not class-based)
- Use `pytest.mark.anyio` for async tests
- Use fixtures for setup/teardown
- Use `@pytest.mark.parametrize` for multiple inputs
- Target 90%+ coverage on modified modules

## Test Organization

```
tests/
├── unit/               # Unit tests
│   ├── services/
│   └── utils/
├── integration/        # Integration tests
│   ├── api/
│   └── database/
├── e2e/                # End-to-end tests
├── fixtures/           # Shared fixtures
└── conftest.py         # pytest configuration
```

## Anti-Patterns

```python
# Bad: Testing implementation details
def test_bad():
    service._internal_cache["key"] = value
    assert service._process() == expected

# Good: Test public API
def test_good():
    result = service.process(input)
    assert result == expected

# Bad: Tests that depend on order
def test_first():
    global_state.value = 1

def test_second():
    assert global_state.value == 1  # Depends on test_first!

# Good: Independent tests
def test_independent():
    state = create_state()
    state.value = 1
    assert state.value == 1
```
