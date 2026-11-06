# Analytics Dashboard Factory: Build Less, Build Better 🚀

**Bayer Challenge @ Since AI Hackathon 2026**

## 📌 Project Overview
Enterprise self-service BI creates speed, but also dashboard sprawl, duplicate logic, unclear ownership, and technical debt. This project aims to solve this by introducing an **AI-powered Analytics Dashboard Factory**.

Instead of mindlessly generating new dashboards for every user request, this system acts as an intelligent gatekeeper and consultant. It parses user intent, searches the existing BI estate (metadata, KPIs, usage stats), and recommends whether to **reuse** an existing dashboard, **modify/consolidate** overlapping assets, or **build** a new governed analytics product.

## 🎯 Goal for the Coding Agent
Your primary task is to help build out the automated, agentic workflow that translates a natural language business request into a governed analytics specification. You will be writing Python scripts, database queries, API integrations, and agent logic.

## 🏗️ Architecture & Workflow
The system is divided into four main Work Packages (WPs):

1. **WP1: Prompt-to-Intent (Clarification Phase)**
   - **Input:** Natural language prompt from a business user.
   - **Action:** Evaluate if the request is clear. If not, trigger a `/grill-me` routine to ask clarifying questions.
   - **Output:** A structured, formal business `Intent`.

2. **WP2: Intent-to-Evidence (Discovery Phase)**
   - **Input:** Structured `Intent`.
   - **Action:** Query the existing BI metadata estate (simulated via MongoDB/TimescaleDB or dataframes). Run an `/explore` function to find overlapping KPIs, existing reports, and lifecycle data.
   - **Output:** `Evidence` mapping out what already exists and suggesting a path forward (Reuse, Retire, Migrate, or Build New).

3. **WP3: Evidence-to-Spec (Governance Phase)**
   - **Input:** `Evidence`.
   - **Action:** Enforce governance rules. Map the request to official Semantic Models and KPI Catalogs. Run `/to-spec`.
   - **Output:** A machine-readable `Spec` (e.g., JSON schema or `DashboardSpec` dataclass) detailing entities, metrics, dimensions, and rationale.

4. **WP4: Spec-to-Report (Generation Phase)**
   - **Input:** Governed `Spec`.
   - **Action:** Render a preview and output a standardized analytics asset definition (e.g., `.pbip` structure for Power BI).

## 🛠️ Tech Stack & Integrations
* **LLM / AI:** Google Gemini API (for intent parsing, semantic matching, and decision-making logic).
* **Orchestration:** n8n (for chaining the agentic workflow).
* **Databases:** MongoDB Atlas (for metadata/catalog storage), TimescaleDB (for usage history).
* **Backend:** Python (Pandas/Scikit-learn for synthetic data enrichment and ML routing logic).

## 📁 Repository Structure (Planned)
* `/data` - Contains the synthetic builder data pack and scripts for data enrichment.
* `/agents` - Python modules for Gemini API interactions (Intent, Evidence, Spec generation).
* `/n8n_workflows` - Exported JSON files of n8n workflows.
* `/api` - FastAPI endpoints to connect the UI/chat interface to the database and agents.

## 🚀 Immediate Next Steps for the Agent
1. Ingest and parse the synthetic BI estate data (`.xlsx` files) to create a searchable mock database (e.g., embedding creation or vector search setup).
2. Build the `Prompt-to-Intent` parser using the Gemini API.
3. Develop the `/explore` function to match intents against existing dashboard metadata.