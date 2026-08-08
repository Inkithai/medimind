# MediMind — AI-Powered Personal Medical Concierge & Clinical Timeline
## Official Presentation Deck for Judges & Technical Evaluation

---

## Slide 1: The Problem
### What Real-World Problem Are We Solving?

```
+-----------------------------------------------------------------------------------+
|                           THE BROKEN MEDICAL EXPERIENCE                           |
|                                                                                   |
|   [ Scattered Paper Scans ]     [ Unstructured PDFs ]      [ Medical Jargon ]     |
|              \                           |                         /              |
|               +--------------------------+------------------------+               |
|                                          v                                        |
|                          CRITICAL HEALTH DATA SILOS                               |
|                                          |                                        |
|         +--------------------------------+--------------------------------+       |
|         v                                v                                v       |
| [ Missed Interactions ]      [ Untracked Lab Trends ]       [ Caregiver Confusion ]
+-----------------------------------------------------------------------------------+
```

#### 1. Fragmented Medical Records
* Patients receive unstructured medical records from different doctors, labs, and hospitals—including paper prescriptions, discharge summaries, PDF test reports, and diagnostic scans.
* Critical health history is trapped in disconnected silos, making it nearly impossible to maintain a unified longitudinal view.

#### 2. Complex Clinical Jargon & Cognitive Overload
* Medical documents are written for clinicians, not patients. Complex terminology, dosage abbreviations, and reference ranges leave patients and caregivers anxious and confused about their own health status.

#### 3. High Risk of Polypharmacy & Medication Errors
* When visiting multiple specialists, patients rarely bring a comprehensive drug list. Overlooked drug-drug interactions, contraindications against allergies, and duplicate therapies cause preventable adverse drug events (ADEs).

#### 4. Lost Longitudinal Trends
* A single normal or abnormal lab report tells only half the story. Tracking vital biomarker trajectories over time (e.g., eGFR, HbA1c, cholesterol, liver enzymes) is manual, tedious, and frequently ignored until acute issues arise.

> **Speaker Note:**  
> *"Judges, every one of us has experienced—or helped a family member navigate—the chaos of scattered medical records. When health data is locked inside unreadable scans and disconnected PDFs, patients face real safety risks from overlooked drug interactions and missed lab trends. MediMind solves this by turning passive medical documents into an intelligent, active health concierge."*

---

## Slide 2: Solution — MediMind
### What Your Application Does

```
+-----------------------------------------------------------------------------------+
|                             MEDIMIND SOLUTION CORE                                |
|                                                                                   |
|  [ Ingest Any Document ]  --->  [ AI Clinical Engine ]  --->  [ Actionable UI ]   |
|   • Scanned PNGs/JPGs            • Structured Extraction       • Unified Timeline |
|   • Multi-page PDFs              • Safety Cross-Checking       • Meds & Warnings  |
|   • Clinical Notes               • Local ONNX RAG              • AI Health Q&A    |
+-----------------------------------------------------------------------------------+
```

#### 1. Intelligent Medical Concierge
* MediMind is a privacy-first AI platform that transforms unstructured medical records into a coherent, organized, and actionable health dashboard.
* It bridges the comprehension gap between clinical documentation and patient understanding without losing medical precision.

#### 2. Automated Structured Extraction
* Upload any combination of prescriptions, lab results, clinical summaries, or doctor's notes. MediMind automatically categorizes documents and extracts structured clinical entities (medications, lab biomarkers, diagnoses, and allergies).

#### 3. Unified Longitudinal Patient Timeline
* Synthesizes isolated visits into a chronological health history. Every prescription, lab test, and physician encounter is linked into a unified patient timeline.

#### 4. Proactive Safety Cross-Checks & Trend Alerts
* Continuously audits the patient's entire medication list against known allergies, chronic conditions, and drug-drug interactions.
* Tracks lab biomarkers over time to highlight clinically significant trajectories before they turn into emergencies.

> **Speaker Note:**  
> *"MediMind is not just an OCR scanner or a general chatbot. It is a purpose-built medical intelligence platform. When a user uploads a stack of medical records, MediMind extracts the clinical facts, constructs a coherent timeline, cross-checks every medication for safety, and allows patients to ask questions against their own health history."*

---

## Slide 3: AI Core
### Deep Clinical Understanding & Multi-Layered Intelligence

```
+-----------------------------------------------------------------------------------+
|                              MEDIMIND AI CORE PIPELINE                            |
|                                                                                   |
|  [ 1. OCR & Vision ]        Multimodal LLM Vision + PyMuPDF / pdfplumber          |
|          v                                                                        |
|  [ 2. LLM Extraction ]      Structured JSON Schema + Reasoning Probe Suppression  |
|          v                                                                        |
|  [ 3. Local RAG ]           In-Process ONNX (all-MiniLM-L6-v2) + ChromaDB Store   |
|          v                                                                        |
|  [ 4. Safety Engine ]       Automated Polypharmacy Audits & Lab Trend Tracking    |
+-----------------------------------------------------------------------------------+
```

#### 1. OCR & Document Understanding
* **Multimodal Vision & Native Parsing:** Combines native PDF text extraction (`pdfplumber` / `PyMuPDF` / `pdfminer.six`) with cutting-edge multimodal vision LLMs (`qwen/qwen3.6-27b`, `gemini-3.6-flash`).
* **Scanned Image Resilience:** Automatically decodes handwritten notes, mobile photos of prescriptions, and multi-page hospital discharge scans.

#### 2. Resilient LLM Processing
* **Structured Output Ladder:** Implements a multi-rung recovery ladder (`_completion_resilient`). Uses strict constrained JSON Schema decoding for supported models, falling back gracefully to JSON Object mode and plain text with tolerant JSON extraction.
* **Reasoning-Tag Suppression (`<think>` Probes):** Automatically detects reasoning models that leak `<think>` preambles and applies process-cached suppression probes to guarantee clean, schema-adherent JSON without burning token budgets.
* **Hard-Quota Circuit Breaker:** Dynamically monitors API rate limits and automatically switches to a configured **OpenRouter fallback** if a primary provider hits hard daily quota exhaustion.

#### 3. RAG (Retrieval-Augmented Generation)
* **Zero-Network Local Embeddings:** Runs `all-MiniLM-L6-v2` locally in-process via ONNX Runtime—no embedding API keys or external network calls required.
* **Structured Chunking:** Embeds structured clinical chunks (medications, lab panels, diagnoses) stored in a per-patient ChromaDB vector store or Supabase vector table.
* **Contextual Answering:** Answers patient Q&A strictly from retrieved timeline facts, preventing hallucination.

#### 4. Safety & Alert Generation
* **Clinical Cross-Checking (`cross_check_prescriptions`):** Generates structured safety reports classifying risks by severity (High / Moderate / Precaution) with actionable clinical advice.
* **Biomarker Trajectory Analysis (`track_lab_trends`):** Automatically maps repeat lab tests, calculates percentage changes, and flags out-of-range clinical trends.

> **Speaker Note:**  
> *"Our AI core is engineered for clinical resilience. Medical documents are messy, and standard LLMs often break on formatting or leak verbose reasoning tags. We built a multi-rung structured recovery ladder with automated reasoning-tag suppression, local zero-network ONNX embeddings for RAG, and an automated safety engine that audits prescriptions against patient allergies and lab trends."*

---

## Slide 4: Key Features
### A Complete Suite for Patient & Clinician Empowerment

```
+-----------------------+-----------------------+-----------------------+
|  1. DOCUMENT UPLOAD   |  2. DATA EXTRACTION   |  3. PATIENT TIMELINE  |
|  • Async multi-file   |  • Meds, labs, notes  |  • Chronological view |
|  • Real-time progress |  • Tolerant JSON      |  • Encounter history  |
+-----------------------+-----------------------+-----------------------+
|  4. MEDICINE HISTORY  |   5. SAFETY ALERTS    |     6. AI CHAT Q&A    |
|  • Active vs past     |  • Polypharmacy audit |  • Conversational RAG |
|  • Dosages & timing   |  • Allergy warnings   |  • Context rewriting  |
+-----------------------+-----------------------+-----------------------+
```

#### 1. Async Multi-File Document Upload
* Drag-and-drop interface supporting batch upload of PDFs, PNGs, and JPEGs.
* Non-blocking background worker pool (`/api/v1/documents?async=true`) with real-time job polling and progress badges.

#### 2. Automated Medical Report Extraction
* Parses document types automatically (`prescription`, `lab_report`, `clinical_note`, `discharge_summary`).
* Extracts medicine names, dosages, frequencies, lab biomarker values, reference ranges, and physician notes into clean JSON.

#### 3. Interactive Patient Timeline
* A unified, searchable chronological history (`TimelineView.tsx`) that consolidates every visit and report into a single view.
* Filter by date range or document category.

#### 4. Comprehensive Medicine History
* Organized medicine dashboard separating active medications from past prescriptions.
* Clear visibility into dosage instructions, treatment duration, and prescribing source.

#### 5. Proactive Safety Alerts & Cross-Checks
* Dedicated Cross-Check Safety Report (`CrossCheckView.tsx`) showing severity-coded warnings.
* Highlights drug-drug interactions, allergy contraindications, and liver/kidney precation alerts based on extracted lab trends.

#### 6. Conversational AI Concierge (RAG Chat)
* Multi-turn Q&A interface allowing patients to ask natural language questions ("Is my amoxicillin safe with my penicillin allergy?", "What was my cholesterol level last March?").
* Uses conversation query rewriting (`conversation.py`) so follow-up questions retrieve the correct context from the local vector store.

> **Speaker Note:**  
> *"From a user's perspective, MediMind offers six core features: seamless multi-file batch uploads, automated clinical data extraction, an intuitive interactive timeline, a consolidated medicine history, severity-graded safety cross-checks, and a conversational RAG assistant that understands conversational context."*

---

## Slide 5: System Architecture
### Modular, Scalable, Privacy-First Technical Design

```
+-----------------------------------------------------------------------------------+
|                              SYSTEM ARCHITECTURE                                  |
|                                                                                   |
|  +--------------------+       HTTP / REST API        +-------------------------+  |
|  |     FRONTEND       | <==========================> |        BACKEND          |  |
|  |  React 18 + Vite   |      JWT Auth / Anon         |    FastAPI + Uvicorn    |  |
|  |  TypeScript + UI   |                              |    Async Background     |  |
|  +--------------------+                              +-------------------------+  |
|                                                                   |               |
|            +------------------------------------------------------+               |
|            |                                                                      |
|            v                                                                      |
|  +-----------------------------------------------------------------------------+  |
|  |                              AI / RAG PIPELINE                              |  |
|  |                                                                             |  |
|  |  [ Extractor & Vision ]  <--->  [ Resilient Ladder ]  <--->  [ RAG Vector ] |  |
|  |   PyMuPDF / pdfplumber            OpenAI SDK Wrapper          ChromaDB /    |  |
|  |   Pillow Image Base64             Reasoning Probes           Local ONNX     |  |
|  +-----------------------------------------------------------------------------+  |
|            |                                      |                               |
|            v                                      v                               |
|  +--------------------+                +--------------------+                     |
|  |  DATABASE & CLOUDS |                |  LLM & AI SERVERS  |                     |
|  |  Supabase Postgres |                |  Groq (gpt-oss/qwen)|                     |
|  |  Cloudinary Storage|                |  Gemini 3.6-Flash  |                     |
|  |  Anon / User Scopes|                |  OpenRouter Auto   |                     |
|  +--------------------+                +--------------------+                     |
+-----------------------------------------------------------------------------------+
```

#### 1. Frontend Layer
* **Framework:** React 18 built with Vite and TypeScript for high-speed client-side rendering.
* **UI/UX Design:** Tailwind CSS with responsive layout components, custom status badges, modal viewers, and real-time polling hooks (`useApi.ts`).

#### 2. Backend API Layer
* **Framework:** Python 3.11 with FastAPI and Uvicorn asynchronous HTTP server.
* **Modular Pipeline Architecture:** Clean separation of concerns across dedicated services:
  * `api.py`: Route validation, authentication, and async worker orchestration.
  * `medical_extractor.py`: Multimodal LLM calling, JSON extraction ladder, and safety cross-checking.
  * `retrieval.py` & `vector_store.py`: Vector chunking, local ONNX embedding, and RAG retrieval.
  * `conversation.py`: Multi-turn session memory, query rewriting, and token-budget summarization.
  * `lab_trends.py`: Longitudinal biomarker analysis and abnormality detection.
  * `jobs.py`: Persistent background job tracking for asynchronous document ingestion.

#### 3. AI / RAG Pipeline
* **Multi-Provider Abstraction:** Universal wrapper over OpenAI SDK supporting Groq, Google Gemini, and OpenRouter.
* **Token Budget & RPM Pacing:** Process-wide call pacers prevent rate limits during concurrent file extractions.
* **Vector Store:** Local ChromaDB collection or Supabase Postgres vector table indexed with zero-network ONNX MiniLM embeddings.

#### 4. Database & Encrypted Storage
* **Relational Storage:** Supabase Postgres (`patient_snapshots`, `jobs`, `chunks` tables) storing structured patient timelines, lab trends, and cross-check reports.
* **Document Archiving:** Encrypted Cloudinary cloud storage for permanent PDF and image archiving.

#### 5. External AI Services & Circuit Breakers
* **Primary LLMs:** Groq (`openai/gpt-oss-120b`, `qwen/qwen3.6-27b`) or Google Gemini (`gemini-3.6-flash`).
* **Auto-Activated Fallback:** Automated circuit breaker that seamlessly routes calls to OpenRouter (`openrouter/free` dynamic router) if the primary provider hits hard quota limits.

> **Speaker Note:**  
> *"Our architecture is clean, modular, and built for production. The React/Vite frontend communicates via REST with a FastAPI Python backend. The AI layer decouples extraction, RAG retrieval, and conversation memory into distinct modules, backed by Supabase Postgres, Cloudinary, and local zero-network ONNX embeddings."*

---

## Slide 6: Demo / User Flow
### Step-by-Step Document Ingestion & Insight Generation

```
  ===================================================================================
                              MEDIMIND USER FLOW DIAGRAM
  ===================================================================================

       +---------------------------------------------------------------------+
       | 1. UPLOAD MEDICAL DOCUMENT                                          |
       |    • Patient uploads 6 files (Prescriptions, Lab Reports, Scans)    |
       |    • Instant async job creation (HTTP 202 Accepted)                 |
       +---------------------------------------------------------------------+
                                          |
                                          v
       +---------------------------------------------------------------------+
       | 2. OCR / EXTRACTION                                                 |
       |    • PyMuPDF / pdfplumber extracts clean text from PDFs             |
       |    • Multimodal Vision LLM converts scanned image Base64 to text     |
       +---------------------------------------------------------------------+
                                          |
                                          v
       +---------------------------------------------------------------------+
       | 3. AI PROCESSING (RESILIENT LADDER)                                 |
       |    • Strict constrained JSON schema extraction                      |
       |    • Automatic reasoning-tag (<think>) suppression probes           |
       |    • Hard-quota auto-fallback circuit breaker                       |
       +---------------------------------------------------------------------+
                                          |
                                          v
       +---------------------------------------------------------------------+
       | 4. STRUCTURED MEDICAL DATA                                          |
       |    • Normalized JSON: Medications, Lab Values, Diagnoses, Allergies |
       |    • Stored in Supabase Postgres & embedded in Local ChromaDB RAG   |
       +---------------------------------------------------------------------+
                                          |
                                          v
       +---------------------------------------------------------------------+
       | 5. TIMELINE / MEDICINES / ALERTS                                    |
       |    • Chronological Timeline & Active Medications View               |
       |    • Severity-Graded Cross-Check Safety Report                      |
       |    • Interactive RAG Chat Concierge with History Memory             |
       +---------------------------------------------------------------------+
```

#### Walkthrough Narrative
1. **Upload:** A user drops 6 medical files (a cardiology discharge summary, blood tests, and prescription photos) into the Upload Page.
2. **Background Processing:** MediMind accepts the batch immediately (`202 Accepted`) and processes files in parallel via background workers.
3. **Extraction & Safety Audit:** The AI Core extracts medications and lab biomarkers, builds the timeline, and runs a comprehensive polypharmacy cross-check against patient allergies.
4. **Instant Actionable Dashboard:** In seconds, the user sees a complete timeline, a clean medication schedule, an highlighted precaution alert for an interaction, and can ask the chat concierge follow-up questions.

> **Speaker Note:**  
> *"Let’s walk through the exact user journey. A patient drops a stack of mixed medical documents into MediMind. Our background worker pool ingests and OCRs each file, runs our structured recovery ladder to extract normalized clinical data, checks for drug interactions, and delivers a clean timeline, active medication list, and safety report in seconds."*

---

## Slide 7: Innovation & Impact
### Why MediMind Stands Out & Who It Transforms

```
+-----------------------------------------------------------------------------------+
|                           INNOVATION & REAL-WORLD IMPACT                          |
|                                                                                   |
|    WHY WE ARE DIFFERENT            WHO BENEFITS                 REAL-WORLD IMPACT |
|                                                                                   |
|  • Resilient AI Ladder          • Patients & Families       • Prevents Medication |
|  • Auto-OpenRouter Fallback     • Elderly & Caregivers        Errors & ADEs       |
|  • Local Zero-Network RAG       • Doctors & Specialists     • Early Biomarker     |
|  • Strict Clinical Schemas      • Chronic Care Patients       Abnormality Alerts  |
+-----------------------------------------------------------------------------------+
```

#### 1. Why MediMind is Different (Technical Innovation)
* **Unmatched Output Resilience:** Medical AI fails when models emit markdown chatter or reasoning dumps. MediMind's automated `<think>` suppression probes and multi-rung JSON ladder ensure 100% parseable structured data.
* **Auto-Configured Circuit Breaker:** Dynamically detects provider quota exhaustion and automatically switches to OpenRouter fallback without dropping patient uploads.
* **Local Zero-Network Privacy:** On-device ONNX embeddings (`all-MiniLM-L6-v2`) ensure patient timeline vectors never leak to third-party embedding servers.

#### 2. Who Benefits
* **Patients & Caregivers:** Navigates complex medical journeys without fear of missing critical dosage rules or drug warnings.
* **Elderly & Polypharmacy Patients:** Empowers patients taking 5+ daily medications by consolidating prescriptions from multiple specialists.
* **Clinicians & Specialists:** Saves doctors 15+ minutes per consultation by providing a synthesized chronological history and pre-audited drug list.

#### 3. Real-World Impact
* **Medication Safety:** Directly mitigates adverse drug events (ADEs)—one of the leading causes of preventable hospitalizations worldwide.
* **Proactive Health Tracking:** Empowers early clinical intervention by tracking subtle multi-year negative biomarker trends before acute symptoms manifest.

> **Speaker Note:**  
> *"What makes MediMind truly innovative is our synthesis of clinical rigor and technical resilience. Unlike generic wrappers, our platform guarantees structured JSON output through reasoning suppression and auto-fallback circuit breakers, while running zero-network local RAG embeddings to protect patient privacy. We are saving doctors time and preventing life-threatening medication errors for patients."*

---

## Slide 8: Technology Stack & Future Roadmap
### Production-Grade Architecture & Scalable Vision

```
+-----------------------------------------------------------------------------------+
|                                 TECHNOLOGY STACK                                  |
|                                                                                   |
|   [ FRONTEND ]         [ BACKEND ]          [ DATABASE ]         [ LLM / RAG ]    |
|   • React 18           • Python 3.11        • Supabase Postgres  • Groq (Llama/   |
|   • Vite + TS          • FastAPI / Uvicorn  • Cloudinary Storage   Qwen Vision)   |
|   • Tailwind CSS       • Pydantic v2        • ChromaDB Vector    • Gemini 3.6     |
|   • Axios / Lucide     • PyMuPDF / Plumber  • Local ONNX MiniLM  • OpenRouter Auto|
+-----------------------------------------------------------------------------------+
```

#### 1. Core Technology Stack
* **Frontend:** React 18, Vite, TypeScript, Tailwind CSS, Lucide Icons, Axios.
* **Backend & API:** Python 3.11, FastAPI, Uvicorn Async Server, Pydantic v2, PyMuPDF, `pdfplumber`, Pillow.
* **Database & Vector Store:** Supabase Postgres (`supabase-py`), Cloudinary Encrypted Storage, ChromaDB / ONNX Runtime (`all-MiniLM-L6-v2`).
* **AI / LLM Engine:** Groq (`gpt-oss-120b`, `qwen3.6-27b`), Google Gemini (`gemini-3.6-flash`), OpenRouter Fallback (`openrouter/free` dynamic router).
* **Cloud & Hosting:** Vercel (Frontend CDN), Render / Railway / Docker (Backend Container), Supabase Cloud.

```
+-----------------------------------------------------------------------------------+
|                                 FUTURE ROADMAP                                    |
|                                                                                   |
|  [ Q3 2026 ] ---> EHR/EMR Integration (HL7 FHIR & Apple Health / Google Fit)      |
|  [ Q4 2026 ] ---> Clinician & Caregiver Portal with Role-Based Access (RBAC)      |
|  [ Q1 2027 ] ---> Multi-Language Voice Concierge & Wearable Biomarker Sync        |
+-----------------------------------------------------------------------------------+
```

#### 2. Future Improvements & Strategic Roadmap
* **EHR & EMR Interoperability:** Support direct ingestion of HL7 FHIR bundles and SMART-on-FHIR hospital records.
* **Wearable & IoT Integration:** Automatically merge Apple Health, Fitbit, and Continuous Glucose Monitor (CGM) time-series data with lab biomarker trends.
* **Caregiver & Physician Sharing Portals:** Secure, permissioned QR-code and link sharing with granular Role-Based Access Control (RBAC) for primary care doctors and family members.
* **Voice & Multilingual Concierge:** Real-time speech-to-speech Q&A in 30+ languages to assist elderly and non-English-speaking patients.

> **Speaker Note:**  
> *"Our technology stack is built on modern, type-safe, high-performance tooling—from React and Vite on the frontend to FastAPI, Supabase, and local ONNX embeddings on the backend. As we look ahead, we are expanding MediMind into a universal health OS with HL7 FHIR hospital interoperability, wearable health sync, and secure clinician sharing portals. Thank you!"*

---

## Summary Table for Judges

| Slide # | Slide Title | Key Takeaway for Judges |
| :---: | :--- | :--- |
| **1** | **The Problem** | Fragmented medical records, complex jargon, and overlooked polypharmacy create serious patient safety risks. |
| **2** | **Solution — MediMind** | An AI concierge that transforms chaotic paper/PDF medical scans into an actionable, structured health timeline. |
| **3** | **AI Core** | Multimodal OCR + Multi-rung structured JSON ladder + Reasoning-tag suppression + Zero-network local ONNX RAG. |
| **4** | **Key Features** | Async upload, medical report extraction, chronological timeline, medicine history, safety alerts, and conversational RAG chat. |
| **5** | **System Architecture** | React/Vite frontend, FastAPI Python backend, Supabase Postgres, Cloudinary, and Groq/Gemini + OpenRouter fallback. |
| **6** | **Demo / User Flow** | 6-file upload $\rightarrow$ OCR/Vision $\rightarrow$ Structured JSON Schema extraction $\rightarrow$ Actionable Timeline, Meds & Safety Alerts. |
| **7** | **Innovation & Impact** | Prevents adverse drug events and tracks lab biomarker trajectories with 100% resilient structured AI decoding. |
| **8** | **Tech Stack & Future** | Modern React + FastAPI + Supabase stack; expanding to HL7 FHIR hospital integration and wearable biomarker sync. |
