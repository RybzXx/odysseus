"""scripts/populate_all_rich_manifests.py
Generates comprehensive, multi-section PROJECT.md manifests for all 21 projects
and synchronizes them into local and phone SQLite databases.
"""

import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r"D:\ai_projects_2026")
LOCAL_AGENT_DIR = ROOT / "OdysseusWork" / "odysseus-agent-1"
LOCAL_DB = LOCAL_AGENT_DIR / "data" / "app.db"

now_iso = datetime.now(timezone.utc).isoformat()

PROJECT_DATA = {
    "AhmedOmarDentist": {
        "id": "proj_685a4b19",
        "slug": "ahmed-omar-dentist",
        "name": "Ahmed Omar Dental Clinic",
        "priority": "normal",
        "status": "active",
        "executive_summary": "Comprehensive branding, visual identity, and patient engagement platform for Ahmed Omar Dental Clinic. Focuses on premium dental care presentation, visual design tokens, treatment showcase portfolios, and appointment booking funnels tailored for dental clinics in Iraq.",
        "objectives": """- Establish a cohesive brand identity (logo, color system, typography, social assets).
- Design and deploy an interactive treatment portfolio showcasing cosmetic dentistry, implants, and orthodontics.
- Build an automated patient appointment intake and SMS/WhatsApp reminder workflow.
- Integrate clinic operational schedules with doctor availability calendars.""",
        "architecture": """### Brand & Visual Identity Architecture
- **Color System**: Curated medical-grade palette (`#0F4C81` Classic Blue, `#20B2AA` Light Sea Green, `#F4F6F9` Platinum White).
- **Design Tokens**: Standardized button radii, shadow elevations, and typographic scale documented in `designs.png` and `Color.png`.
- **Patient Intake Engine**: Multi-step web form capturing patient history, treatment interests, and preferred appointment time slots.""",
        "structure": """### Directory & Asset Topology
- `Color.png`: Clinic brand color swatches, primary/secondary/accent HEX definitions.
- `LogoAhmed.jpg`: Master vector and raster logo assets in high resolution.
- `designs.png`: UI wireframes for clinic landing page and treatment modal screens.
- `PROJECT.md`: Project manifest and live task tracking.""",
        "spec": """### Technical Specification & Invariants
- **Responsive Layout**: Mobile-first viewport optimization for iOS and Android web browsers.
- **Asset Optimization**: WebP image compression for portfolio galleries under 150KB per slide.
- **Privacy & Security**: Zero client-side caching of confidential patient medical information.""",
        "tasks": [
            ("Finalize master clinic brand color system and typography guidelines", True),
            ("Build responsive patient booking intake form with WhatsApp integration", False),
            ("Deploy interactive before-and-after smile transformation gallery", False)
        ]
    },

    "AIconnection": {
        "id": "proj_738d2a9e",
        "slug": "ai-connection",
        "name": "Distributed AI Connection Hub",
        "priority": "high",
        "status": "active",
        "executive_summary": "High-performance distributed inference routing and pooled LLM connectivity hub. Links the workstation's local GPU Ollama instance (RTX 3070) with remote edge devices (Samsung Galaxy S24 Ultra Termux node) across private Tailscale mesh networks with automatic failover, health checks, and pooled benchmark harnesses.",
        "objectives": """- Orchestrate zero-latency OpenAI-compatible API streaming across distributed local nodes.
- Maintain persistent, encrypted Tailscale connection between PC workstation and mobile Termux nodes.
- Run continuous automated model benchmarking (`benchmark_pooled_granite`, `benchmark_pooled_muse`).
- Provide unified model discovery and dynamic load-balancing for local agent instances.""",
        "architecture": """### Distributed Network Topology
- **Local GPU Server**: Ollama running on PC host (`http://100.82.8.53:11434`) serving quantized LLMs (`qwen2.5:7b`, `granite3.2:8b`, `deepseek-r1:8b`).
- **Edge Client Node**: Samsung Galaxy S24 Ultra running Termux Proot Ubuntu (`http://100.117.120.93:7000`).
- **Tunneling & Mesh**: Private Tailscale overlay network with mutual wireguard authentication.
- **Benchmark Sequence Harness**: PowerShell orchestrators managing warmup rounds, token-per-second measuring, and temperature parameter sweeps.""",
        "structure": """### Key Scripts & Topology
- `DISTRIBUTED_SETUP_GUIDE.md`: Step-by-step connection manual, port forwarding, and Tailscale ACL rules.
- `run_pooled_server.ps1`: Automated launcher for pooled inference listeners with background restart guards.
- `run_pooled_benchmark_sequence.ps1`: Matrix testing script evaluating latency, TTFT, and generation throughput.
- `rerun_pooled_harness_only.ps1`: Regression verification script for failed endpoint connections.""",
        "spec": """### Performance & Reliability Invariants
- **Time to First Token (TTFT)**: Sub-350ms across Tailscale mesh network for 7B parameter models.
- **Connection Timeout**: Strict 10s socket connect timeout with automatic fallback to secondary node.
- **SSE Stream Integrity**: Chunked UTF-8 JSON streaming with newline delimiters preserving tool call JSON.""",
        "tasks": [
            ("Establish Tailscale mesh routing between PC GPU and S24 Ultra Termux", True),
            ("Run matrix performance benchmarks for Qwen 2.5 and Granite 3.2 models", True),
            ("Implement automatic failover proxy routing for agent tool calling", False)
        ]
    },

    "AlreemSilverWeb": {
        "id": "proj_d238dd68",
        "slug": "alreem-silver-web",
        "name": "Al-Reem Silver Jewelry E-Commerce",
        "priority": "high",
        "status": "active",
        "executive_summary": "Modern, localized luxury e-commerce web platform for Al-Reem Silver Jewelry (مجوهرات الريم للفضة). Features bilingual Arabic/English storefront, real-time inventory management via Supabase, shopping cart state persistence, high-resolution product showcases, and seamless WhatsApp/checkout order placement.",
        "objectives": """- Deliver a responsive, high-aesthetic e-commerce experience tailored for Iraqi and regional jewelry buyers.
- Support complete bilingual localization (Arabic RTL and English LTR) with zero layout shift.
- Integrate Supabase database for real-time catalog syncing, price tiering, and order capture.
- Provide custom jewelry filtering (sterling 925 silver, gemstones, rings, necklaces, custom engravings).""",
        "architecture": """### System Architecture
- **Frontend**: Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS with custom luxury color palette.
- **Localization**: `next-intl` powering dynamic translation catalogs in `messages/ar.json` and `messages/en.json`.
- **Backend & Database**: Supabase SSR (`@supabase/ssr`, `@supabase/supabase-js`) managing products, categories, and customer orders.
- **Asset Pipeline**: High-resolution image optimization with Next.js Image component and Supabase Storage CDN.""",
        "structure": """### Codebase & Component Structure
- `app/`: Next.js App Router root with `[locale]` internationalization routing.
- `components/`: Modular component library (CartDrawer, ProductGrid, FilterBar, CurrencySelector).
- `design_handoff_alreem_store/`: Figma design tokens, luxury typography scale, and banner assets.
- `messages/`: Translated JSON dictionary files (`ar.json`, `en.json`).
- `PROJECT.md`: Project spec and sprint checklist.""",
        "spec": """### Functional & Non-Functional Specifications
- **Localization**: 100% Arabic (RTL) support with custom Cairo font typography.
- **Performance**: Lighthouse score > 90 on mobile devices with sub-1.2s Largest Contentful Paint.
- **Cart Persistence**: LocalStorage sync with Supabase cart reconciliation upon login.""",
        "tasks": [
            ("Complete bilingual Next.js 15 storefront structure with Tailwind CSS", True),
            ("Integrate Supabase product catalog and category filters", True),
            ("Implement checkout order placement workflow with direct WhatsApp integration", False)
        ]
    },

    "ApplicationBilW": {
        "id": "proj_dc29486b",
        "slug": "application-bilw",
        "name": "Bil Weekend Mobile Application",
        "priority": "high",
        "status": "active",
        "executive_summary": "Native and cross-platform mobile application architecture for 'بالعطلة' (Bil Weekend), Iraq's premier experiential weekend travel and cultural tour platform. Provides interactive itinerary browsing, real-time seat reservation, departure countdowns, offline tour passes, and live guide communication.",
        "objectives": """- Build intuitive mobile customer journey from tour discovery to instant digital ticket generation.
- Enable offline access to itinerary timelines, meeting points, hotel check-in vouchers, and guide contacts.
- Provide real-time push notifications for itinerary updates, weather advisories, and departure reminders.
- Sync seamlessly with the Bil Weekend operations hub and web booking database.""",
        "architecture": """### Mobile Architecture & Design
- **State Management**: Reactive state providers managing authentication, active bookings, and offline cache.
- **UX Workflow**: Detailed screen flows defined in `SPEC_Phase1.md` and `Application Concept_ “بالعطلة” (Bil Weekend) V2.md`.
- **Navigation Topology**: Bottom navigation bar with Explore, My Trips, Saved Tours, and Profile.
- **Offline Storage**: Local SQLite/Hive key-value store caching itinerary details for remote excursions.""",
        "structure": """### Project Hierarchy
- `app/`: Core application UI screens (TourDetails, BookingFlow, TicketPass, LiveTimeline).
- `appcore/`: Core business logic, API services, geolocation helpers, and state models.
- `SPEC_Phase1.md`: Complete functional specification of phase 1 mobile MVP.
- `PROJECT_RECORD.md`: Historic decisions, API contracts, and roadmap milestones.""",
        "spec": """### Technical Contract
- **Offline Support**: Tour tickets and day-by-day itineraries viewable with zero internet connectivity.
- **Biometric Authentication**: FaceID / Fingerprint login support for quick booking access.
- **Deep Linking**: Dynamic links resolving directly to specific tour package landing screens.""",
        "tasks": [
            ("Draft comprehensive mobile application concept and UX flow specifications", True),
            ("Implement interactive tour package discovery screen and itinerary timeline widget", False),
            ("Build offline digital boarding pass with QR code validation", False)
        ]
    },

    "Blogs": {
        "id": "proj_14d3f8d2",
        "slug": "blogs-eridu",
        "name": "Cultural Heritage & History Blogs",
        "priority": "normal",
        "status": "active",
        "executive_summary": "Editorial and research content pipeline focused on Iraqi Mesopotamian civilization, ancient historical landmarks, and tourism storytelling. Combines academic historical synthesis with engaging multimedia articles to promote cultural tourism.",
        "objectives": """- Produce in-depth historical articles on ancient cities (Eridu, Babylon, Ur, Uruk, Samarra).
- Build automated LLM prompt pipelines for historical document synthesis and storytelling.
- Package verified cultural insights into bite-sized content for tourism marketing and educational apps.
- Curate photographic and archaeological assets with verified citations.""",
        "architecture": """### Publishing & Synthesis Pipeline
- **Content Engine**: Structured markdown publishing framework with frontmatter metadata for SEO.
- **Extraction Prompts**: `Blog_Extraction_Prompt.md` orchestrating historical fact verification and narrative flow.
- **Asset Archive**: High-resolution archaeological photography (`Eridu2Pics.jpg`) and historical maps.""",
        "structure": """### Directory Topology
- `Eridu_ The Birthplace of Babylon and the Dawn of Civilization.md`: Featured long-form investigative article.
- `Blog_Extraction_Prompt.md`: LLM prompt template for generating historical synthesis blogs.
- `Eridu2Pics.jpg`: Verified archaeological site imagery.
- `PROJECT.md`: Editorial calendar and research checklist.""",
        "spec": """### Editorial Guidelines
- **Fact-Checking**: Every historical claim cross-referenced with academic archaeological publications.
- **Readability**: Dual-audience structure (engaging traveler overview + deep historical appendix).
- **SEO Formatting**: Semantic headings, meta descriptions, and image alt attributes.""",
        "tasks": [
            ("Complete and publish feature article on Eridu: The Birthplace of Civilization", True),
            ("Develop automated prompt pipeline for regional history blog extraction", False),
            ("Integrate blog publishing feed into Rehlat Al-Utla content hub", False)
        ]
    },

    "HotelWebsite": {
        "id": "proj_77fe147e",
        "slug": "hotel-website",
        "name": "Downtown Hotel Web Portal",
        "priority": "normal",
        "status": "active",
        "executive_summary": "Full-featured web portal and room booking showcase for a premier downtown hotel. Features virtual room tours, direct reservation engines, amenities showcases, meeting space booking, and multi-currency pricing for international and local guests.",
        "objectives": """- Deliver a modern, high-converting digital portal for hotel room exploration and direct booking.
- Showcase hotel amenities (restaurants, spa, fitness center, conference halls) with rich media.
- Integrate interactive booking calendar with room availability and seasonal price tiering.
- Provide guest services portal (room service menus, local attraction guides, airport transfers).""",
        "architecture": """### Frontend & Portal Architecture
- **Web Interface**: Clean semantic HTML5, CSS3 Grid/Flexbox layouts, responsive mobile navigation.
- **Asset Hierarchy**: High-resolution imagery in `HotelMainInfoNonCompressed/` optimized for web in `HotelMainWeb/`.
- **Booking Engine**: Date range picker with guest count selectors, room tier filtering, and price calculators.""",
        "structure": """### Directory Layout
- `HotelMainWeb/`: Production web assets, HTML templates, stylesheets, and client scripts.
- `HotelMainInfoNonCompressed/`: Source high-resolution photography, floorplans, and marketing assets.
- `PROJECT.md`: Web portal specification and development roadmap.""",
        "spec": """### Portal Specifications
- **Cross-Browser Compatibility**: Full parity across Chrome, Safari, Edge, and Firefox.
- **Media Optimization**: Lazy-loaded galleries with responsive srcset image delivery.
- **Form Validation**: Strict email, international phone number, and stay duration validation.""",
        "tasks": [
            ("Organize high-resolution hotel media assets and room tier categories", True),
            ("Build interactive room availability calendar and reservation calculator", False),
            ("Implement guest amenity showcase and dining menu visualizers", False)
        ]
    },

    "LifeData": {
        "id": "proj_2c6b748f",
        "slug": "life-data",
        "name": "LifeData Health & Telemetry",
        "priority": "normal",
        "status": "active",
        "executive_summary": "Personal biometric telemetry data lake and health intelligence system. Ingests, parses, and aggregates historical fitness, heart rate, sleep quality, and activity logs from Samsung Health and Google Takeout exports to discover lifestyle correlations and trends.",
        "objectives": """- Parse large multi-gigabyte Google Takeout and Samsung Health JSON/CSV/XML telemetry exports.
- Normalize disparate health metrics (resting HR, HRV, REM sleep stages, daily step counts) into a unified time-series schema.
- Generate automated weekly health summaries and visual trend dashboards.
- Provide local, privacy-first biometric analytics with zero third-party cloud data exposure.""",
        "architecture": """### Data Lake & Analytics Engine
- **Ingestion Pipeline**: Python parsers extracting continuous sensor streams from `Takeout/` archives.
- **Data Normalization (`lifeatlas/`)**: Standardized schema mapping heart rate intervals, GPS workouts, and sleep cycles.
- **Storage Layer**: Local SQLite database with DuckDB / Pandas analytics for rapid aggregations.""",
        "structure": """### Directory & Ingestion Structure
- `Takeout/`: Raw exported Google Takeout and Samsung Health archives.
- `lifeatlas/`: Core Python parsing modules, normalization scripts, and data models.
- `LifeDatacodespace.code-workspace`: VS Code configuration with pre-configured Python telemetry extensions.
- `PROJECT.md`: Data schema definitions and processing checklist.""",
        "spec": """### Privacy & Invariant Requirements
- **100% Air-Gapped / Local**: Health data is processed entirely on the local workstation without external API transmission.
- **Data Sanitization**: Automated removal of PII and GPS home bounding box coordinates from shared exports.
- **Timezone Normalization**: Strict UTC timestamp alignment with local offset tracking across international travel.""",
        "tasks": [
            ("Configure LifeData ingestion workspace and archive structure", True),
            ("Build automated parser for Samsung Health and Google Takeout sleep data", False),
            ("Generate monthly cardiovascular trend reports and HRV correlation graphs", False)
        ]
    },

    "MaxwellEMvisual": {
        "id": "proj_fd60c13b",
        "slug": "maxwell-em-visual",
        "name": "Maxwell EM Field Visualizer",
        "priority": "normal",
        "status": "active",
        "executive_summary": "Interactive, educational physics simulation and visualization suite for Maxwell's electromagnetic equations. Features real-time HTML5 Canvas visualizers for EM wave propagation, motional EMF Faraday induction, and GPS satellite signal triangulation.",
        "objectives": """- Provide intuitive, real-time interactive visualizers for complex electromagnetic field concepts.
- Simulate transverse electromagnetic (TEM) plane wave propagation in various dielectric media.
- Model Faraday's law of induction and Lorentz force on moving conductors in magnetic fields.
- Visualize GPS satellite time-delay signal triangulation and geometric dilution of precision (GDOP).""",
        "architecture": """### Simulation Engine & Graphics
- **Rendering Layer**: High-performance HTML5 Canvas 2D / WebGL rendering at 60 FPS.
- **Mathematical Core**: Real-time vector calculus numerical solvers for Maxwell's curl and divergence equations.
- **Server**: Lightweight Node.js Express server (`server.js`) serving static interactive visualizers.""",
        "structure": """### Visualizer Modules
- `em-wave-simulator/`: Interactive canvas for E-field and B-field sinusoidal orthogonal wave propagation.
- `motional-emf/`: Physics simulation of conductor rods moving through uniform magnetic flux.
- `gps-simulator/`: Interactive 4-satellite constellation positioning and pseudorange solver.
- `index.html`, `index.css`, `server.js`: Visualizer hub entry point and control panels.""",
        "spec": """### Physics & Graphics Invariants
- **Frame Rate**: Smooth 60 FPS animation loop with requestAnimationFrame.
- **Numerical Accuracy**: Symplectic Euler integration preserving energy conservation in field simulations.
- **Interactive Controls**: Real-time sliders for frequency, wavelength, medium permittivity, and conductor velocity.""",
        "tasks": [
            ("Implement 3D orthogonal EM wave propagation canvas simulator", True),
            ("Build motional EMF Faraday law conductor bar visualizer", True),
            ("Add relativistic Doppler shift controls and dielectric boundary reflections", False)
        ]
    },

    "MedicalEcommerce": {
        "id": "proj_63d9c15b",
        "slug": "medical-ecommerce",
        "name": "Iraqi Medical E-Commerce Research",
        "priority": "normal",
        "status": "active",
        "executive_summary": "Comprehensive market feasibility study, supplier competitive intelligence, and platform architecture research for a specialized medical and dental equipment e-commerce platform in Iraq. Analyzes market gaps, pricing transparency, logistics constraints, and clinic procurement habits.",
        "objectives": """- Analyze market size, supplier margins, and distribution channels for dental and medical clinics across Iraq.
- Benchmark existing local suppliers and regional B2B healthcare procurement platforms.
- Formulate an end-to-end B2B e-commerce platform model with transparent pricing and credit term management.
- Address cold-chain storage logistics, regulatory compliance, and equipment servicing contracts.""",
        "architecture": """### Research & Market Synthesis
- **Market Study**: `Iraqi Medical E-Commerce Feasibility.md` evaluating Baghdad, Erbil, and Basra clinic demand.
- **Competitor Matrix**: `Iraqi Dental Platforms Analysis.md` mapping local distributors, product availability, and margins.
- **Strategic Log**: `DECISION-LOG.md` tracking business model hypotheses, platform monetization, and risk mitigations.""",
        "structure": """### Research Documents
- `Iraqi Medical E-Commerce Feasibility.md`: Core feasibility report, financial models, and operational plan.
- `Iraqi Dental Platforms Analysis.md`: Deep dive into dental consumables, composite resins, and equipment distributors.
- `Research Findings Report.md`: Executive findings synthesized for stakeholders.
- `PROJECT.md`: Research milestones and platform specification.""",
        "spec": """### Platform Architecture Requirements
- **Catalog Structure**: Multi-tier taxonomy (Dental Consumables, Surgical Instruments, Diagnostic Imaging, Orthodontics).
- **Pricing Tiers**: Role-based wholesale vs retail pricing with minimum order quantities (MOQ).
- **Compliance**: Verified Ministry of Health / Kimadia registration tracking for all cataloged medical devices.""",
        "tasks": [
            ("Complete comprehensive feasibility study on Iraqi dental supply chain", True),
            ("Map competitive landscape of dental equipment suppliers in Baghdad and Erbil", True),
            ("Design wireframes and database schema for B2B clinic procurement platform", False)
        ]
    },

    "New_Operrations": {
        "id": "proj_1a4ecf2a",
        "slug": "new-operations",
        "name": "Bil Weekend Operations Portal",
        "priority": "high",
        "status": "active",
        "executive_summary": "Internal operational logistics and tour dispatch portal for the Bil Weekend team. Manages passenger manifest generation, tour guide assignments, coach driver dispatch, meal catering orders, hotel room block allocations, and real-time expense reconciliation.",
        "objectives": """- Automate weekly passenger manifest creation from web and mobile bookings.
- Manage driver, tour leader, and local guide dispatch schedules with instant contact sheets.
- Coordinate hotel room allotments, dietary preferences, and site entrance ticket blocks.
- Track real-time trip operating expenses, vendor disbursements, and profit margin reconciliation.""",
        "architecture": """### Operations Workflow Engine
- **Dispatch Engine**: Automated assignment of staff to scheduled tour itineraries.
- **Manifest Generator**: Generates formatted PDF/Excel passenger manifests with emergency contacts and seat allocations.
- **Financial Ledger**: Real-time logging of operating cash advances, toll fees, hotel payments, and guide compensations.""",
        "structure": """### Operations Directory
- `operations/`: Weekly trip rosters, dispatch schedules, driver contacts, and hotel vouchers.
- `manifests/`: Customer passenger lists formatted for checkpoints and hotel check-in.
- `PROJECT.md`: Operational sprint tasks and system documentation.""",
        "spec": """### Operational Invariants
- **Checkpoint Ready**: Manifests must print in bilingual Arabic/English format compliant with Iraqi tourism security protocols.
- **Audit Trail**: Every edit to passenger assignments or fee collections logged with timestamp and operator ID.
- **Instant Export**: Sub-2-second generation of complete 50-passenger coach manifests.""",
        "tasks": [
            ("Establish weekly tour dispatch manifest templates and driver assignment sheets", True),
            ("Automate passenger check-in reconciliation with web booking database", True),
            ("Build real-time mobile expense tracking dashboard for tour leaders", False)
        ]
    },

    "OdysseusWork": {
        "id": "proj_3850125c",
        "slug": "odysseus-work",
        "name": "Odysseus Agent Platform Hub",
        "priority": "high",
        "status": "active",
        "executive_summary": "Core repository and operational workstation for the Odysseus dual-agent platform. Odysseus is an autonomous, local-first AI agent system featuring hybrid File-as-Spec project management, full SQLite indexing, MCP tool integration, ChromaDB semantic vector search, real-time web UI, and distributed multi-device synchronization.",
        "objectives": """- Maintain zero-lag bidirectional synchronization between disk manifests (`PROJECT.md`) and SQLite indexing (`app.db`).
- Provide unified web management hub with 4-tier progressive project overviews and interactive task checklists.
- Orchestrate MCP server ecosystem (image generation, memory vectors, RAG documents, email dispatch).
- Seamlessly mirror project workspaces across PC workstation and Samsung S24 Ultra Termux node.""",
        "architecture": """### Core Platform Architecture
- **Backend**: FastAPI with Uvicorn, SQLAlchemy ORM, SQLite (`app.db`), Pydantic request validation.
- **Frontend**: Vanilla ES6 modules (`static/js/projects.js`, `markdown.js`, `chat.js`, `ui.js`) with zero build step requirements.
- **Markdown Engine**: Custom GFM-compliant markdown compiler (`markdownModule.mdToHtml`) with KaTeX and Mermaid diagram support.
- **MCP Subsystem**: FastMCP JSON-RPC microservers managing memory, vector search, email, and shell execution.
- **Multi-Device Mesh**: Tailscale SFTP + SSH bridge syncing live data between PC host and mobile Termux Linux.""",
        "structure": """### Workspace Hierarchy
- `odysseus-agent-1/`: Primary agent installation containing `core/`, `routes/`, `src/`, `static/`, `mcp_servers/`, and `data/`.
- `odysseus-agent-2/`: Secondary agent workspace.
- `odysseus_endpoint.py`: S24 Ultra proot endpoint registrar.
- `phone_connection.py`: Tailscale connection credentials and paths.
- `PROJECTS_CATALOG_RECORD.md`: Permanent system record of all 21 project repositories and slugs.
- `PROJECT.md`: Platform manifest and active development backlog.""",
        "spec": """### System Invariants
- **Zero-Restart Updates**: Project additions and task edits reflect instantly in active running instances without process restarts.
- **Permission Neutrality**: Projects with `owner = NULL` are universally visible across all authenticated sessions.
- **Disk-DB Equivalence**: Any disk edit to `PROJECT.md` is guaranteed to reconcile with SQLite upon sync.""",
        "tasks": [
            ("Build 4-tier overview sub-tabs and rich markdown rendering engine", True),
            ("Implement interactive manifest task checklist with live disk synchronization", True),
            ("Deploy automated multi-project cross-device sync pipeline to Samsung S24 Ultra", True),
            ("Extend MCP server capabilities for automated code review and test runners", False)
        ]
    },

    "OperationsAutomationSrv": {
        "id": "proj_a5bfd7fc",
        "slug": "operations-automation-srv",
        "name": "Operations Automation Service",
        "priority": "normal",
        "status": "active",
        "executive_summary": "Background asynchronous task scheduler and webhook event worker for Bil Weekend operations. Automates recurring batch jobs, customer notification emails, booking status transitions, and external API integrations.",
        "objectives": """- Run reliable background cron scheduling for tour lifecycle events (48h reminder, 24h departure alert, post-trip review request).
- Process incoming webhooks from payment gateways and WhatsApp business APIs.
- Monitor system health, memory utilization, and network connection uptime across agent nodes.
- Maintain persistent execution logs with automated alert dispatch on task failures.""",
        "architecture": """### Service Architecture
- **Engine**: Python AsyncIO daemon with APScheduler cron triggers.
- **Job Store**: SQLite database maintaining job execution state, retry counters, and output logs.
- **Notification Gateway**: SMTP client and WhatsApp cloud API wrappers dispatching customer messages.""",
        "structure": """### Service Hierarchy
- `server.py`: Main daemon entry point initializing scheduled tasks and webhook listeners.
- `tasks/`: Modular job routines (email_reminders, db_cleanup, price_sync, health_audit).
- `config.json`: Service credentials, interval definitions, and log levels.
- `logs/`: Rotating execution logs and error diagnostics.""",
        "spec": """### Reliability Invariants
- **Idempotent Execution**: Scheduled jobs can run multiple times without duplicating customer communications or financial charges.
- **Graceful Shutdown**: SIGINT / SIGTERM signals allow active jobs to finish or checkpoint cleanly before process termination.
- **Retry Policy**: Exponential backoff (1m, 5m, 15m) for failed webhook delivery attempts.""",
        "tasks": [
            ("Implement core async scheduler daemon with APScheduler and SQLite job store", True),
            ("Build automated 48-hour pre-trip reminder and departure notification jobs", False),
            ("Set up centralized error alerting webhook to Odysseus operations channel", False)
        ]
    },

    "OudProject": {
        "id": "proj_000614a1",
        "slug": "oud-project",
        "name": "Oud Perfume Brand Research",
        "priority": "normal",
        "status": "active",
        "executive_summary": "Branding formulation, fragrance tier research, market analysis, and visual packaging design for a luxury Arabian artisanal Oud perfume line. Formulates signature fragrance pyramids, luxury bottle aesthetics, and regional brand positioning.",
        "objectives": """- Define signature fragrance profiles (Dehn Al Oud, Cambodian Oud, Taif Rose, Smoky Amber).
- Analyze regional luxury fragrance competitors (Abdul Samad Al Qurashi, Arabian Oud, Ajmal, niche artisanal houses).
- Design luxury packaging concepts (crystal flacons, wooden presentation boxes, embossed metallic labels).
- Build digital boutique concept and storytelling narrative around sustainable agarwood harvesting.""",
        "architecture": """### Brand Development Framework
- **Fragrance Architecture**: Olfactory pyramid breakdown (Top notes, Heart notes, Base notes) documented in `Oud Perfume Brand Research.md`.
- **Competitor Benchmarking**: Matrix in `research/` analyzing price-per-ml, bottle design, and longevity ratings.
- **Packaging Tokens**: Color palettes (Deep Obsidian, Brushed Gold, Royal Burgundy, Emerald Green).""",
        "structure": """### Project Hierarchy
- `Oud Perfume Brand Research.md`: Comprehensive brand concept, fragrance profiles, and demographic target report.
- `research/`: Competitor price surveys, packaging material suppliers, and fragrance oil sourcing notes.
- `PROJECT.md`: Development roadmap and creative milestones.""",
        "spec": """### Creative & Quality Standards
- **Authenticity Narrative**: Documented provenance of pure agarwood oil distillations.
- **Packaging Specs**: Custom 50ml and 100ml heavy-weight crystal flacons with magnetic zamak caps.
- **Brand Tone**: Prestigious, poetic, deeply rooted in Mesopotamian and Gulf luxury heritage.""",
        "tasks": [
            ("Complete master fragrance profile formulations and olfactory pyramid document", True),
            ("Conduct regional luxury Oud market competitor price and packaging analysis", True),
            ("Create 3D bottle packaging mockups and luxury e-boutique wireframes", False)
        ]
    },

    "Pharmacy": {
        "id": "proj_01f4bd81",
        "slug": "pharmacy-digitization",
        "name": "Iraqi Pharmacy Digitization",
        "priority": "normal",
        "status": "active",
        "executive_summary": "In-depth market intelligence, regulatory analysis, and digital transformation architecture for Iraq's pharmaceutical sector. Analyzes Kimadia public procurement tables, WHO essential drug lists, private pharmacy inventory supply chains, and point-of-sale digitization opportunities.",
        "objectives": """- Map the pharmaceutical supply chain across state procurement (Kimadia) and private pharmacy networks.
- Reconcile WHO Essential Medicines List against live Iraqi procurement award tables (`Kimadia_drug_awarding_table_Apr2026.pdf`).
- Design an integrated pharmacy inventory, prescription verification, and drug interaction alert system.
- Address supply chain bottlenecks, counterfeit drug mitigation, and barcoded batch tracking.""",
        "architecture": """### Sector Research & System Model
- **Regulatory Framework**: Detailed in `Iraqi Pharmacy Digitization Analysis.md` and `Iraq_Pharmacy_Market_Status_2026.md`.
- **Procurement Reconciliation**: Cross-analysis of `Kimadia_drug_awarding_table_Apr2026.pdf` against `Iraq_Essential_Drugs_List_WHO_2014.pdf`.
- **Data Access Architecture**: `GUDEA_Data_Access.md` defining secure health data access layers and drug registries.""",
        "structure": """### Research Documents
- `Iraqi Pharmacy Digitization Analysis.md`: Master sector analysis and digital transformation roadmap.
- `Iraq_Pharmacy_Market_Status_2026.md`: Current market sizing, distribution hubs, and private sector pain points.
- `Research_Synthesis_Global_Reference.md`: Global benchmarks (FDA, EMA, Jordan JFDA) applied to Iraqi context.
- `Design_Decisions.md`: Architecture trade-offs for pharmacy POS and supply chain tracking software.
- `Kimadia_drug_awarding_table_Apr2026.pdf`: Official government drug procurement data.
- `Iraq_Essential_Drugs_List_WHO_2014.pdf`: WHO baseline pharmaceutical catalog.""",
        "spec": """### Software & Compliance Specs
- **Data Standards**: GS1 DataMatrix barcode scanning for batch and expiration date validation.
- **Drug Interaction Engine**: Real-time cross-referencing of contraindications and dosage thresholds.
- **Offline Resilience**: Full POS dispensing operations functional during internet outages with queue sync.""",
        "tasks": [
            ("Synthesize Iraqi pharmaceutical market regulatory and supply chain analysis", True),
            ("Extract and cross-reference Kimadia 2026 procurement award tables with WHO EML", True),
            ("Design database schema for pharmacy point-of-sale inventory and batch tracking", False)
        ]
    },

    "Productsearch": {
        "id": "proj_c104aa83",
        "slug": "product-search",
        "name": "Product Search Engine",
        "priority": "normal",
        "status": "active",
        "executive_summary": "High-precision product discovery, web scraping, and price intelligence engine. Designed to crawl, normalize, and match e-commerce product catalogs across regional Iraqi and Middle Eastern retailers with spec-driven extraction, fuzzy deduplication, and automated change tracking.",
        "objectives": """- Crawl and scrape regional e-commerce portals with robust rate-limiting and anti-blocking resilience.
- Normalize messy unstructured product titles, specifications, and prices into standardized schemas.
- Implement high-performance fuzzy matching to reconcile identical products across different merchants.
- Track price history, availability alerts, and discount trends over time.""",
        "architecture": """### Engine Architecture
- **Parser Core (`ps/`)**: Spec-driven DOM parsing and regex extraction pipelines.
- **Crawler Subsystem (`sources/`)**: Site-specific crawler plugins with proxy rotation and header emulation.
- **Search & Ranking (`searches/`)**: Inverted index and vector similarity search for product discovery.
- **Test Suite (`tests/`)**: Automated regression test cases for parsing accuracy and price extraction.""",
        "structure": """### Directory & Module Layout
- `SPEC.md`: Master architectural specification, parsing contracts, and error handling invariants.
- `ps/`: Core search parser, tokenization, and price normalizers.
- `sources/`: Site adapters, extraction rules, and selector configurations.
- `searches/`: Saved search pipelines, query benchmarks, and ranking profiles.
- `tests/`: Automated unit and integration test suite.
- `README.md`, `PROJECT.md`: Setup instructions and sprint tasks.""",
        "spec": """### Parsing & Search Contracts
- **Precision Requirement**: > 99.5% price and currency extraction accuracy on valid HTML pages.
- **Deduplication**: Jaccard + Levenshtein fuzzy string distance matching with confidence thresholds.
- **Graceful Degradation**: Crawler automatically falls back to secondary selector heuristics when layouts mutate.""",
        "tasks": [
            ("Define comprehensive parser specifications and crawler architecture in SPEC.md", True),
            ("Implement core product extraction engine and price normalizer in ps/", False),
            ("Build automated multi-source comparison and price drop alert pipeline", False)
        ]
    },

    "RehlatWebsite": {
        "id": "proj_61653616",
        "slug": "rehlat-website",
        "name": "Rehlat Al-Utla Travel Platform",
        "priority": "high",
        "status": "active",
        "executive_summary": "Production web platform and customer booking portal for Rehlat Al-Utla (`dev.rehlatalutla.iq`), Iraq's premier leisure travel and holiday package agency. Built with Next.js 15, React 19, Tailwind CSS, and Supabase SSR, providing immersive tour discovery, date-based booking, provider management, and synchronized sheet ingestion.",
        "objectives": """- Provide high-performance, mobile-first travel booking experience for leisure travelers across Iraq.
- Connect directly with live Google Sheets B2B sourcing pipeline (`WebsiteConnection`) for real-time tour updates.
- Support comprehensive provider administration, package customization, and booking state workflows.
- Deliver sub-second page loads with optimal image caching and Supabase SSR data queries.""",
        "architecture": """### Full-Stack Architecture
- **Framework**: Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS, Lucide React icons.
- **Forms & Validation**: `react-hook-form` paired with `zod` schema validation for all booking flows.
- **Backend & Auth**: Supabase SSR (`@supabase/ssr`, `@supabase/supabase-js`) managing tours, bookings, and users.
- **Pipeline Integration**: Ingests normalized tour packages directly from the `WebsiteConnection` studio pipeline.""",
        "structure": """### Codebase & Route Hierarchy
- `app/`: App router with public catalog, package details (`/packages/[id]`), checkout, and `/admin` provider portal.
- `components/`: Modular UI system (PackageCard, ItineraryViewer, BookingModal, FilterSidebar, Header).
- `docs/`: Technical documentation (`PIPELINE_ARCHITECTURE.md`, `CACHE_POLICY.md`, `SCHEMA.md`).
- `SETUP.md`, `SPEC_Phase1.md`, `SupabaseWithinAGY.md`: Developer environment guides and specifications.
- `PROJECT.md`: Project spec and sprint backlog.""",
        "spec": """### Technical & Business Invariants
- **Real-Time Consistency**: Package prices and seat availability reflect live database state with zero stale cache.
- **Mobile First**: 100% feature parity and touch-optimized navigation on smartphones.
- **Security**: Strict Row-Level Security (RLS) policies on Supabase tables preventing unauthorized customer data access.""",
        "tasks": [
            ("Build Next.js 15 travel platform frontend with responsive package explorer", True),
            ("Implement Supabase SSR database integration and admin provider portal", True),
            ("Deploy automated Google Sheets ETL synchronization pipeline with live website database", True),
            ("Implement online payment gateway integration with local Iraqi payment providers", False)
        ]
    },

    "SBAH_Ticketing": {
        "id": "proj_be8673da",
        "slug": "sbah-ticketing",
        "name": "SBAH Antiquities Ticketing",
        "priority": "high",
        "status": "active",
        "executive_summary": "Revenue projection model, visitor validation algorithms, and ticketing digitization study for Iraq's State Board of Antiquities and Heritage (الهيئة العامة للاثار والتراث). Analyzes historical museum and archaeological site ticket revenues to build modern electronic ticketing systems.",
        "objectives": """- Validate and reconcile historical ticket sales across national museums and archaeological sites (Babylon, Ur, Hatra, National Museum).
- Build mathematical revenue projection models forecasting electronic ticketing adoption and foreign tourist influx.
- Eliminate ticket leakage and cash handling risks through QR-code digital ticket validation.
- Provide real-time visitor flow analytics and revenue dashboards for ministry leadership.""",
        "architecture": """### Financial & Modeling Framework
- **Validation Engine**: Detailed in `VALIDATION_RECORD.md` verifying cell-identical calculations with government records.
- **Master Model**: `SBAH_Revenue_Validation.xlsx` containing historical visitor counts, ticket pricing tiers, and revenue formulas.
- **Source Data**: `تقرير الهيئة العامة للاثار والتراث (1).xlsx` containing multi-year archaeological site ticket records.""",
        "structure": """### Directory & Data Assets
- `VALIDATION_RECORD.md`: Methodology, error bounds, and mathematical proof of revenue formulas.
- `SBAH_Revenue_Validation.xlsx`: Validated master financial model with appended audit sheet.
- `تقرير الهيئة العامة للاثار والتراث (1).xlsx`: Primary government historical dataset.
- `Desktopview.png`: Dashboard wireframe for ministry oversight portal.
- `PROJECT.md`: Project milestones and validation tasks.""",
        "spec": """### Modeling Invariants
- **Zero Discrepancy**: 100% mathematical reconciliation with official ministry historical audits.
- **Tiered Pricing**: Model incorporates separate fee structures for Iraqi citizens, students, and foreign visitors.
- **Conservative Forecasting**: Baseline projections apply 15% safety margin on foreign tourist growth rates.""",
        "tasks": [
            ("Audit and validate historical SBAH archaeological site ticket datasets in Excel", True),
            ("Build validated revenue projection model and validation documentation", True),
            ("Design electronic QR-code gate scanner workflow for major archaeological sites", False)
        ]
    },

    "ServicesComaprison": {
        "id": "proj_88bf541f",
        "slug": "services-comparison",
        "name": "Iraqi Tourism Services Comparison",
        "priority": "normal",
        "status": "active",
        "executive_summary": "Comprehensive B2B comparative intelligence and benchmarking study of Iraq's leading travel agency service providers (Alzaeem Group, Dar Al Raheem, Rehlat Al Safari). Analyzes flight routes, hotel allocations, package pricing, margin spreads, and destination coverage across 30+ operational sheets.",
        "objectives": """- Conduct sheet-by-sheet comparative analysis across all three major travel agency provider spreadsheets.
- Benchmark pricing structures across popular destinations (Beirut, Baku, Istanbul, Antalya, Trabzon, Dubai).
- Identify hotel tier differences, airline charter commitments, and seasonal price fluctuations.
- Synthesize actionable B2B procurement insights for the Rehlat Al-Utla travel platform.""",
        "architecture": """### Data Extraction & Analysis Model
- **Comparative Report**: `Comparison_Report.md` providing in-depth synthesis of every destination and package tier.
- **Methodology**: `methodology_and_considerations.md` detailing extraction heuristics, currency conversions, and normalization rules.
- **Master Matrix**: `Provider_Comparison_Dashboard.xlsx` aggregating cross-provider rates into unified comparative views.""",
        "structure": """### Analysis Documents & Sheets
- `Comparison_Report.md`: Full coverage analytical report comparing Alzaeem, Dar Al Raheem, and Safari.
- `methodology_and_considerations.md`: Analytical framework and data normalization methodology.
- `Provider_Comparison_Dashboard.xlsx`: Interactive comparative dashboard model.
- `Alzaeem_Group.xlsx`, `DarAlRaheem.xlsx`, `RehlatAlSafari.xlsx`: Source provider B2B package spreadsheets.
- `sheets_list.txt`: Directory of all 30+ analyzed destination worksheets.""",
        "spec": """### Benchmarking Standards
- **Exhaustive Scope**: Analysis covers 100% of visible worksheets across all three provider files.
- **Currency Normalization**: Real-time conversion between USD and IQD using market exchange rates.
- **Room Tier Categorization**: Standardized mapping of single, double, triple, and child-with-bed rates.""",
        "tasks": [
            ("Perform exhaustive sheet-by-sheet extraction across all provider spreadsheets", True),
            ("Generate comprehensive B2B comparative analysis report and pricing dashboard", True),
            ("Feed standardized hotel and pricing benchmarks into WebsiteConnection sourcing pipeline", True)
        ]
    },

    "TermuxSamsung": {
        "id": "proj_37505ce0",
        "slug": "termux-samsung",
        "name": "Termux Mobile Inference Node",
        "priority": "high",
        "status": "active",
        "executive_summary": "24/7 headless Linux server and mobile AI inference node running on a Samsung Galaxy S24 Ultra via Termux and proot Ubuntu. Serves as a persistent edge compute station hosting Odysseus server instances, ChromaDB vector databases, automated background sync workers, and distributed AI proxy relays.",
        "objectives": """- Maintain a persistent 24/7 Linux server environment on mobile hardware with zero battery thermal throttling.
- Host active Odysseus backend server (`0.0.0.0:7000`) with persistent storage mapped to `~/odysseus-data/`.
- Run ChromaDB vector store instance (`127.0.0.1:8100`) for on-device semantic retrieval.
- Orchestrate distributed AI model inference and benchmark execution across mobile CPU/NPU and PC GPU.""",
        "architecture": """### Mobile Infrastructure Architecture
- **Host Layer**: Termux on Android 14 / OneUI 6.1 with battery optimization exclusions and persistent wake-locks.
- **Container Layer**: Proot-distro Ubuntu 24.04 ARM64 container hosting Python 3.12/3.14 virtual environments.
- **Network Layer**: Tailscale mesh IP (`100.117.120.93`) exposing SSH (`:8022`), Odysseus (`:7000`), and Chroma (`:8100`).
- **Storage Layer**: Direct symlink binding between container filesystem and Termux `/data/data/com.termux/files/home/odysseus-data/`.""",
        "structure": """### Scripts & Guides
- `headless_linux_setup_guide.md`: Comprehensive setup and maintenance manual for S24 Ultra headless Linux node.
- `Doc1.md`: Migration guide and performance tuning documentation.
- `ai_mode.ps1`, `ai_mode_config.json`: Remote orchestration scripts for benchmarking and power profile tuning.
- `benchmark_agent_models.py`: Automated on-device benchmark harness measuring TTFT and token velocity.
- `antigravity_direct_gemini.py`: Direct API proxy relay.""",
        "spec": """### Operational Invariants
- **Uptime**: 99.9% availability over Tailscale with auto-restart daemons on Termux boot.
- **Thermal Policy**: Throttling threshold locked at 42°C with automated workload backoff.
- **Data Persistence**: All SQLite databases and Chroma vector collections survive container rebuilds.""",
        "tasks": [
            ("Set up headless 24/7 Termux proot Ubuntu environment on Samsung Galaxy S24 Ultra", True),
            ("Deploy and configure active Odysseus server with ChromaDB vector store", True),
            ("Implement automated cross-device workspace synchronization with PC workstation", True)
        ]
    },

    "WebsiteConnection": {
        "id": "proj_c77b5a49",
        "slug": "website-connection",
        "name": "Tour Itinerary & Map Studio Connector",
        "priority": "normal",
        "status": "active",
        "executive_summary": "Specialized data transformation, interpretation mapping, and ETL synchronization pipeline connecting B2B travel agency Google Sheets with the live Rehlat Al-Utla website database. Features Map Studio (:8765) and Itinerary Studio (:8766) visual tools for visual column mapping, anomaly detection, price extraction, and automated database sync.",
        "objectives": """- Automate end-to-end extraction from unstructured, erratic travel agency B2B spreadsheets into structured database models.
- Provide visual Map Studio for non-technical operators to author and adjust per-sheet column interpretation maps.
- Provide Itinerary Studio for generating stable tour lookup codes, day-by-day itineraries, and hotel catalogs.
- Execute unified 1-click sync pushing validated package deltas directly to the live website Supabase database.""",
        "architecture": """### Pipeline Architecture
- **Map Studio (`:8765`)**: Web-based visual tool for assigning semantic meaning to messy spreadsheet columns and rows.
- **Itinerary Studio (`:8766`)**: Visual interface for previewing generated day-by-day itineraries and destination highlights.
- **Sourcing Engine (`itinerary_data/`)**: Python parsing core executing fuzzy hotel matching, currency conversion, and delta detection.
- **Unified Sync (`unified_sync_2026-07-06.md`)**: Shared push mechanism syncing validated package deltas to Supabase.""",
        "structure": """### Pipeline Documentation & Modules
- `README.md`: Studio execution manual and architecture overview.
- `map_studio_2026-07-05.md`: Map Studio session record, interpretation map architecture, and rule engines.
- `itinerary_layer_2026-07-05.md`: Itinerary transformation layer and stable lookup code documentation.
- `exhaustive_sheet_analysis.md`: Detailed analysis of all 30+ sheets across AlZaeem, DarAlRaheem, and Safari.
- `sheet_templates.md`: Reverse-engineered schema specifications for all provider templates.
- `Studio.bat`: One-click batch launcher starting both Map Studio and Itinerary Studio.""",
        "spec": """### Pipeline & Sync Invariants
- **Zero Silent Failures**: Any unparseable row or mutated column triggers visual warnings in Map Studio before sync.
- **Delta Tracking**: Only updated prices, dates, or hotels trigger database mutations, preserving existing user bookings.
- **Audit Logging**: Every sync creates a timestamped JSON artifact documenting exact additions, edits, and deletions.""",
        "tasks": [
            ("Build Map Studio (:8765) and Itinerary Studio (:8766) visual parsing interfaces", True),
            ("Implement unified 1-click sync pipeline pushing validated packages to website DB", True),
            ("Harden parsing rules for DarAlRaheem and AlZaeem complex multi-destination sheets", True),
            ("Add automated scheduled polling of provider Google Sheets with Slack/WhatsApp alerts", False)
        ]
    },

    "weddingproject": {
        "id": "proj_a57e2142",
        "slug": "wedding-project",
        "name": "Wedding Planning Web Platform",
        "priority": "normal",
        "status": "active",
        "executive_summary": "Interactive, highly aesthetic digital wedding invitation, guest RSVP management, venue directions, and event schedule web platform. Built with Next.js 15, React 19, TypeScript, Tailwind CSS, and Vercel Blob, featuring animated invitations, digital guestbook, live countdown, and instant RSVP confirmation.",
        "objectives": """- Deliver a personalized, animated digital invitation experience for wedding guests across mobile and desktop.
- Manage real-time guest RSVP submissions (attendance confirmation, plus-one counts, dietary preferences).
- Provide interactive venue location maps, parking instructions, and timeline of the wedding celebrations.
- Include a digital guestbook allowing attendees to submit blessings, congratulations, and candid photos.""",
        "architecture": """### Platform Architecture
- **Frontend**: Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS with elegant typography and animations.
- **RSVP Subsystem**: Dynamic form with Zod validation, instant database storage, and confirmation messaging.
- **Media Storage**: `@vercel/blob` for fast, CDN-cached guestbook photo uploads and high-res couple galleries.
- **Interactive Map**: Embedded interactive map with single-tap Google Maps / Apple Maps navigation links.""",
        "structure": """### Project Hierarchy
- `app/`: Next.js App Router root with invitation landing page, RSVP flow, and schedule timeline.
- `components/`: UI components (CountdownTimer, RsvpModal, GuestbookFeed, VenueMap, PhotoGallery).
- `lib/`: Vercel Blob helpers, database connection utilities, and form validators.
- `PROJECT.md`: Project spec and development checklist.""",
        "spec": """### Design & Performance Invariants
- **Visual Polish**: Fluid entrance animations, elegant typography (serif display + modern sans), and gold/rose gold accents.
- **Mobile Experience**: Optimized for vertical mobile viewports (where 95% of guests view invitations).
- **RSVP Reliability**: Instant client-side validation preventing duplicate submissions from the same guest name.""",
        "tasks": [
            ("Design responsive wedding invitation landing page with countdown timer", True),
            ("Build digital guest RSVP intake form with plus-one and dietary selections", True),
            ("Integrate Vercel Blob media storage for interactive guestbook photo uploads", False)
        ]
    }
}


def build_manifest_text(proj_info):
    task_lines = "\n".join([f"- [{'x' if t[1] else ' '}] {t[0]}" for t in proj_info["tasks"]])
    
    body = f"""# {proj_info["name"]}

{proj_info["executive_summary"]}

## Objectives

{proj_info["objectives"]}

{proj_info["architecture"]}

{proj_info["structure"]}

{proj_info["spec"]}

## Active Tasks

{task_lines}

## Execution Log

- `{now_iso[:10]}`: Comprehensive multi-section manifest populated with architectural, structural, and technical specifications.
"""

    frontmatter = f"""---
id: {proj_info["id"]}
name: {proj_info["name"]}
slug: {proj_info["slug"]}
status: {proj_info["status"]}
priority: {proj_info["priority"]}
owner: null
created_at: '{now_iso}'
updated_at: '{now_iso}'
links: []
---

"""
    return frontmatter + body


def main():
    print(f"--- Populating Rich Manifests for {len(PROJECT_DATA)} Projects ---")
    
    conn = sqlite3.connect(LOCAL_DB)
    cur = conn.cursor()
    
    for folder_name, info in PROJECT_DATA.items():
        folder_path = ROOT / folder_name
        if not folder_path.exists():
            print(f"[SKIP] Folder not found: {folder_path}")
            continue
            
        manifest_path = folder_path / "PROJECT.md"
        manifest_text = build_manifest_text(info)
        manifest_path.write_text(manifest_text, encoding="utf-8")
        print(f"[OK] Written: {folder_name}/PROJECT.md ({len(manifest_text)} bytes)")
        
        # Also update local SQLite database
        task_total = len(info["tasks"])
        task_completed = sum(1 for t in info["tasks"] if t[1])
        
        cur.execute("SELECT id FROM projects WHERE slug = ?", (info["slug"],))
        row = cur.fetchone()
        if row:
            proj_id = row[0]
            cur.execute("""
                UPDATE projects
                SET name = ?, description = ?, status = ?, priority = ?, owner = NULL,
                    folder_path = ?, manifest_path = ?, task_total = ?, task_completed = ?,
                    updated_at = ?
                WHERE id = ?
            """, (info["name"], info["executive_summary"], info["status"], info["priority"],
                  str(folder_path), str(manifest_path), task_total, task_completed, now_iso, proj_id))
        else:
            proj_id = info["id"]
            cur.execute("""
                INSERT INTO projects (id, slug, name, description, status, priority, owner, folder_path, manifest_path, task_total, task_completed, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
            """, (proj_id, info["slug"], info["name"], info["executive_summary"], info["status"], info["priority"],
                  str(folder_path), str(manifest_path), task_total, task_completed, now_iso, now_iso))
            
        # Refresh tasks in SQLite
        cur.execute("DELETE FROM project_tasks WHERE project_id = ?", (proj_id,))
        for idx, t in enumerate(info["tasks"]):
            cur.execute("""
                INSERT INTO project_tasks (id, project_id, title, completed, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (f"ptask_{info['slug'][:4]}_{idx}", proj_id, t[0], 1 if t[1] else 0, idx, now_iso, now_iso))
            
    conn.commit()
    conn.close()
    print("\nLocal SQLite app.db successfully updated with all rich project data!")


if __name__ == "__main__":
    main()
