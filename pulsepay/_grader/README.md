# PulsePay Grader Test Suite

## 1. What this folder is

This folder contains the internal grader test suite used by Signal auto-grading.
It is never shipped to candidates and is excluded from container images through `.dockerignore`.

## 2. How tests are structured

Each task has its own folder and a single `test_grader.py` file.
All grader tests are tagged with `@pytest.mark.grader` and `@pytest.mark.task("task_id")`.

## 3. Weights

Weights are defined in `_grader/grader_config.json`.
The grading runner reads those weights during scoring; test code does not enforce weighting.

## 4. Running locally (for task authors)

```bash
pytest _grader/ -m grader --asyncio-mode=auto -v
```

## 5. Adding a new task

- Create a new task folder under `_grader/`.
- Add a `test_grader.py` with hermetic async tests.
- Add the task entry in `grader_config.json`.
- Ensure task test weights sum to 100.
- Include the task branch name in config metadata.

## 6. Important

These tests require a real PostgreSQL test database.
Set `DATABASE_URL` to a dedicated test database before running and never point grader tests at production.
