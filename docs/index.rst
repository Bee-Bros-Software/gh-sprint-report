gh-sprint-report
=====================

Sprint reporting for GitHub Projects boards. Reads a Projects v2 board over
GraphQL, accumulates daily snapshots so burndown history survives carryover,
and renders a PowerPoint sprint review deck with native editable charts.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   usage
   upload
   api

Quick start
-----------

.. code-block:: console

   $ export GITHUB_PROJECTS_TOKEN=github_pat_...
   $ sprint-report --org your-org --project 4 snapshot
   $ sprint-report --org your-org --project 4 report \
         --iteration current --output sprint-review.pptx

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
