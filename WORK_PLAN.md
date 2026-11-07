# SinceAI integration and Streamlit frontend

Preserve the existing Python and n8n behavior while using a Python dashboard.

1. Keep bounded, authenticated FastAPI-to-n8n contracts with no POST retries or silent local fallback.
2. Keep read-only integrated dashboard records, authenticated governance forwarding and the deterministic replenishment service.
3. Put the application in the framework-neutral `application/` directory and preserve its existing private `.env`.
4. Replace the browser frontend and Node tests with Streamlit, Python Plotly and native AppTest coverage. Remove the obsolete static assets and browser CDN imports.
5. Preserve chat, chart/table/CSV rendering, warnings, receipts, saved refresh, morning briefings, role isolation and stewardship.
6. Validate identity before server-side UI calls; keep local listeners on loopback and support trusted reverse-proxy identity for hosting.
7. Update every active path reference, launch instruction and integration document.

Pre-migration baseline: 57 Python tests and 8 previous frontend behavior checks passed; 9 original tests require the Excel data pack. Existing `.env.example` deletion and untracked `gemini.md` remain user changes. The application directory lock was traced to its development server, which was stopped for the rename and will be restarted from the new location after verification.

The live n8n workflow export and legacy-record migration remain external deployment dependencies; no live workflow calls, database writes or migrations are needed for frontend verification.

Completed: 77 Python tests passed, including native Streamlit AppTest flows and server-side UI authentication/transport tests. Nine Excel-based tests still skip without the data pack. Python compilation, dependency consistency and diff checks passed. Current source/documentation scans found no obsolete framework names or browser CDN imports. All 22 expected tracked application files were relocated, and the private environment file was preserved. FastAPI and Streamlit were restarted from `application/`; local HTTP startup checks succeeded. Live n8n workflows were not invoked.
