# n8n workflow exports

The live workflow export was not supplied and is not reconstructed from the brief. Export the actual existing workflow here before editing it; exclude credentials and pinned sample business data.

Expected workflows:

- Governed KPI Chat Pipeline: `POST /webhook/kpi-chat`.
- KPI Governance: `POST /webhook/kpi-governance`.

Both require Header Auth with `X-KPI-Webhook-Secret`. Follow the exact request/response, shared-record and lifecycle contracts in [the application integration guide](../application/INTEGRATION.md). The chat workflow can call the authenticated Python replenishment endpoint described there; it must not call `/api/ask` back.

Keep n8n as the only writer of integrated chart, request and approval records. Do not publish until every response branch, scope check and governance transition has been verified. No workflow has been deployed by the local application changes.
