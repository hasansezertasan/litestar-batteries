.. A 7-character "=" underline (the length of "Modules") is treated as a
   merge-conflict separator by ``git diff --check`` / ``check-merge-conflict``;
   keep this underline longer than the title to avoid the false positive.

Modules
=========

An overview of the packages that make up ``litestar_batteries``.
The API reference below is generated automatically from the source docstrings.

Health (``litestar_batteries.health``)
--------------------------------------

Drop-in liveness/readiness plugin: ``GET /health`` plus ``GET /health/ready``.

.. automodule:: litestar_batteries.health.controller

.. automodule:: litestar_batteries.health.models

.. automodule:: litestar_batteries.health.plugin

Idempotency (``litestar_batteries.idempotency``)
-------------------------------------------------

Deduplicates retried unsafe requests carrying an ``Idempotency-Key`` header.

.. automodule:: litestar_batteries.idempotency.claims

.. automodule:: litestar_batteries.idempotency.middleware

.. automodule:: litestar_batteries.idempotency.models

.. automodule:: litestar_batteries.idempotency.plugin


.. Document each new battery here as the project grows.
