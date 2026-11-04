Usage
=====

As a library
------------

Look up the installed distribution version:

.. literalinclude:: examples/version_lookup.py
   :language: python
   :caption: examples/version_lookup.py

For short interactive snippets embedded in prose, the ``docs-doctest`` task
executes ``>>>`` blocks too:

.. doctest::

   >>> from litestar_batteries import HealthConfig, IdempotencyConfig
   >>> HealthConfig().path
   '/health'
   >>> IdempotencyConfig().ttl
   86400
