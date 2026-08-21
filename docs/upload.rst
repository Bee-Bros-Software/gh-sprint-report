Delivering decks to SharePoint or OneDrive
==========================================

The ``report`` command can upload the generated deck through Microsoft Graph
so it lands where the team already works.

App registration
----------------

Create an Entra ID app registration and grant it an **application** permission
(not delegated, since the workflow runs unattended).

Prefer ``Sites.Selected``. An administrator then authorises the registration
against the single target site:

.. code-block:: text

   PATCH https://graph.microsoft.com/v1.0/sites/{site-id}/permissions

``Files.ReadWrite.All`` also works but grants read and write across every site
in the tenant. That breadth is difficult to justify
for a tool that writes one PowerPoint file a week.

Credentials are read from the environment:

============================  ==========================================
``GRAPH_TENANT_ID``           Tenant GUID or domain
``GRAPH_CLIENT_ID``           Application (client) ID
``GRAPH_CLIENT_SECRET``       Client secret
============================  ==========================================

SharePoint
----------

.. code-block:: console

   $ sprint-report --org acme --project 4 report \
       --sharepoint-host acme.sharepoint.com \
       --sharepoint-site /sites/Engineering \
       --upload-folder "Sprint Reviews"

The deck goes into the site's default document library. Missing folders are
created. A file of the same name is replaced, so each Monday overwrites rather
than accumulating duplicates — pass ``--upload-name`` if you would rather keep
a dated history.

OneDrive
--------

.. code-block:: console

   $ sprint-report --org acme --project 4 report \
       --onedrive-user phil@acme.com \
       --upload-folder "Sprint Reviews"

SharePoint and OneDrive destinations are mutually exclusive.

Limits
------

Uploads use Graph's simple content ``PUT``, capped at roughly 4 MiB. A
generated deck is typically under 200 KiB, so this is not a practical
constraint; a file above the limit raises rather than silently truncating.

Throttling responses (429) honour ``Retry-After`` and are retried.
