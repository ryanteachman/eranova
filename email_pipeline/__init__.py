"""Return Trip email pipeline: turns inbound freight emails into proposed quotes and draft replies.

Ryan's backend imports email_pipeline.routes and email_pipeline.tools while it starts up, so it is
loaded here first. Otherwise running the pipeline on its own (the CLI) would import our modules
halfway, then the backend, then our modules again: a circular import.
"""

import backend  # noqa: F401
