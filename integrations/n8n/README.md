# Optional n8n governance scan

The bundled [workflow](build-less-governance-scan.json) reads SinceAI's chart
registry directly from MongoDB every five minutes. It writes certification or
retirement proposals and audit records. A person approves or rejects proposals;
the scan does not itself change chart lifecycle status.

This integration is optional. The [FastAPI + Vue application](../../application/README.md)
starts without n8n. For this bundled scan, n8n and the app share MongoDB; n8n does
not need to reach your local API over the network.

## Rules implemented in the workflow

| Proposal | Eligibility |
| --- | --- |
| Certify | Chart is `active` and has at least two used roles or at least three uses. |
| Retire | Chart is `active` or `certified` and has exceeded the inactivity threshold. |

Certification is checked first, as in the backend registry suggestions. A pending
proposal with the same fingerprint **and action** suppresses another proposal of
that kind. The inactivity threshold is a constant `RETIRE_IDLE_MINUTES=43200`
(30 days) inside the workflow's `Valitse ehdotettavat` code node. It does not
read the Python process environment.

## Setup

1. Allow the n8n deployment's outbound IP addresses in Atlas network access and
   create/configure a database credential with the necessary read/write access.
   Use an explicit allowlist rather than opening database access to all addresses.
2. Import `build-less-governance-scan.json` into your n8n instance.
3. Assign the intended MongoDB credential to `Hae kaaviot`,
   `Hae odottavat ehdotukset`, `Tallenna ehdotus` and `Kirjaa audit logiin`.
   Use the same target database as the application's `MONGODB_DB`.
4. Check the workflow's collection/field mappings before saving. The Finnish node
   names above are retained in the JSON even when the application UI uses English.
5. Test manually against a demo/test database, then activate scheduling if wanted.

The scan reads `chart_registry` and pending `proposals`; it inserts into `proposals`
and `audit_log`. Proposal fields include `_id`, `fingerprint`, `title`, `action`,
`status`, `evidence`, `created_at` and `source`.

## Manual demo

1. Ask the same monthly delivery-reliability question under plant director and
   shift supervisor. With the same filters, the app should reuse one chart and
   record both roles. Check the registry rather than assuming a specific chart ID.
2. Run the workflow manually. Check `Tallenna ehdotus` for an eligible proposal.
3. In the app's Data steward view, inspect the proposal and audit entry. Approve or
   reject it only after reviewing the evidence. An approved certification changes
   the chart to `certified`.
4. Run the workflow again. A matching pending proposal should not be duplicated;
   a chart already certified is no longer eligible for certification.

For a short retirement demo, change the workflow constant to `5` and set the
backend's `RETIRE_IDLE_MINUTES=5`, then restart the backend. Both values must be
changed separately. Choose a demo chart that is not taking the certification
branch first, and restore the intended threshold afterwards.

## Callback/playbook integration is separate

`N8N_WEBHOOK_URL` in the app optionally notifies a separate approval playbook.
`PUBLIC_BASE_URL` supplies the callback URL in that notification. The bundled
MongoDB scan does not require either setting. `localhost` in a callback refers to
the recipient's machine and will not reach your local app from a cloud service.

When `WEBHOOK_SECRET` is configured, `POST /api/registry/decision` requires the
matching `X-Webhook-Secret`. The current browser approval action does not send
that header, so use an authorized API/playbook caller in that configuration.
Never embed this secret in frontend JavaScript. Most other app routes remain
unauthenticated; a callback secret is not a complete deployment security model.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Timeout selecting MongoDB server | Network allowlist, DNS/connectivity and deployment egress IP. |
| Authentication failed | Database credential, permissions and connection string. |
| No charts returned | Database selection and whether the registry is populated. |
| No proposals emitted | Eligibility rules, certification priority, threshold and pending action/fingerprint pairs. |
| Duplicate proposals | Pending-proposal read node/mapping and node execution settings. |
| Missing inserted fields | MongoDB insert mappings listed above. |
| Decision returns HTTP 401 | Required `X-Webhook-Secret`; do not expose the value in the browser. |

See the [architecture](../../docs/architecture.md#n8n-and-approvals) for the two
integration paths and the [project guide](../../README.md) for local startup.
