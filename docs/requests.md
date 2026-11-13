# Cross-owner requests

- **Ryan → Asher:** the backend loads your code on import, so please expose:
  - `email_pipeline/tools.py`: register tools with `from backend.agent.registry import tool`
    and executors (for example `send_reply`) with `from backend.agent.actions import executor`.
    An `approve`-tier tool returns `{title, summary, payload, confidence, reasoning}`; the
    executor receives that `payload` and returns a result dict.
  - `email_pipeline/routes.py`: a Flask `Blueprint` named `bp` with no `url_prefix`; it is
    mounted at `/api/email`.
  - `washouts` table: the FSMA rule runs `SELECT 1 FROM washouts WHERE trailer_number = ?`.
    Please include a `trailer_number` column, or tell me the real column name.
  - To run the agent from an email: `from backend.agent.loop import run_agent` →
    `run_agent("email", message, context={...})`.
