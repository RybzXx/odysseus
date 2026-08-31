"""scripts/catalog_and_integrate.py

Comprehensive cataloging, Git initialization, PROJECT.md generation,
and Odysseus database / filesystem junction integration.
"""

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(r"D:\ai_projects_2026")
ODYSSEUS_DIR = WORKSPACE_ROOT / "OdysseusWork" / "odysseus-agent-1"
ODYSSEUS_DATA = ODYSSEUS_DIR / "data"
ODYSSEUS_PROJECTS_DIR = ODYSSEUS_DATA / "projects"

# Add Odysseus to path so we can import core.database and projects_manager
sys.path.insert(0, str(ODYSSEUS_DIR))
from core.database import SessionLocal, Project, ProjectTask, ProjectLink
from src.projects_manager import parse_tasks_from_markdown, serialize_project_manifest

# Complete Project Registry
PROJECT_DEFINITIONS = [
    {
        "folder": "AhmedOmarDentist",
        "slug": "ahmed-omar-dentist",
        "name": "Ahmed Omar Dental Clinic",
        "category": "Brand & Media Assets",
        "priority": "normal",
        "status": "active",
        "git_profile": "data",
        "summary": "Brand assets, design systems, visual identity, and web presence planning for Ahmed Omar Dental Clinic.",
        "tech_stack": [
            "Branding Assets & Color Palettes",
            "Graphic Design (Logo, Visual Mockups)",
            "Web Appointment Specifications",
        ],
        "objectives": [
            "Establish consistent clinic visual brand identity across all physical and digital touchpoints.",
            "Design seamless appointment booking and patient inquiry workflows.",
            "Prepare digital service catalogs for cosmetic and general dental procedures.",
        ],
        "tasks": [
            {"title": "Review logo variations and finalize typography and color palette", "completed": False},
            {"title": "Draft digital appointment booking feature requirements", "completed": False},
            {"title": "Catalog procedure pricing and treatment showcase visuals", "completed": False},
        ],
    },
    {
        "folder": "AIconnection",
        "slug": "ai-connection",
        "name": "Distributed AI Connection Hub",
        "category": "AI & Infrastructure",
        "priority": "high",
        "status": "active",
        "git_profile": "python",
        "summary": "Distributed LLM connection pool, pooled benchmark harness, and high-throughput model serving orchestrator.",
        "tech_stack": [
            "PowerShell Automation & Orchestration",
            "Python Inference Clients & Benchmarks",
            "Local & Remote LLM Serving Endpoints",
            "Distributed Failover Harness",
        ],
        "objectives": [
            "Provide low-latency pooled model serving across local and edge hardware.",
            "Automate benchmark sequences to quantify token generation throughput and TTFT.",
            "Ensure resilient fallback between local model shards and cloud API endpoints.",
        ],
        "tasks": [
            {"title": "Benchmark pooled inference latency across candidate model weights", "completed": False},
            {"title": "Harden connection pool failover mechanisms and health checks", "completed": False},
            {"title": "Document distributed setup guide and endpoint configuration parameters", "completed": True},
        ],
    },
    {
        "folder": "AlreemSilverWeb",
        "slug": "alreem-silver-web",
        "name": "Al-Reem Silver Jewelry E-Commerce",
        "category": "Web & E-Commerce",
        "priority": "high",
        "status": "active",
        "git_profile": "node",
        "summary": "Modern, responsive e-commerce web platform for Al-Reem Silver Jewelry, built with Next.js 15, React, and Tailwind CSS.",
        "tech_stack": [
            "Next.js 15 & React 19 (App Router)",
            "TypeScript & Tailwind CSS",
            "ESLint & PostCSS Tooling",
            "Al-Reem Silver Jewelry Design System",
        ],
        "objectives": [
            "Deliver an elegant luxury shopping experience for handcrafted silver jewelry.",
            "Implement high-performance image optimization for detailed jewelry pieces.",
            "Provide localized Arabic UI with smooth cart and checkout flows.",
        ],
        "tasks": [
            {"title": "Implement responsive jewelry product grid and category filters", "completed": True},
            {"title": "Integrate shopping cart state management and checkout flow", "completed": False},
            {"title": "Connect WhatsApp direct ordering and local payment options", "completed": False},
        ],
    },
    {
        "folder": "ApplicationBilW",
        "slug": "application-bilw",
        "name": "Bil Weekend Mobile Application",
        "category": "Mobile & Operations",
        "priority": "high",
        "status": "active",
        "git_profile": "flutter",
        "summary": "Cross-platform mobile application and backend service for Bil Weekend tourism, tour booking, and itinerary experiences in Iraq.",
        "tech_stack": [
            "Flutter 3 & Dart (Android, iOS, Web)",
            "Supabase Backend (Auth, Database, Storage)",
            "ECIES / Cryptographic Security (Node.js backend)",
            "PostgreSQL & Realtime Sync",
        ],
        "objectives": [
            "Enable travelers to discover, book, and track curated weekend trips across Iraq.",
            "Provide real-time trip updates, live itinerary schedules, and booking tickets.",
            "Maintain end-to-end data security and synchronized operational state.",
        ],
        "tasks": [
            {"title": "Complete Phase 1 mobile UI flows and widget layouts", "completed": True},
            {"title": "Verify Supabase authentication, database schema, and migration scripts", "completed": False},
            {"title": "Implement offline caching for tour schedules and traveler vouchers", "completed": False},
        ],
    },
    {
        "folder": "Blogs",
        "slug": "blogs-eridu",
        "name": "Cultural Heritage & History Blogs",
        "category": "Editorial & Research",
        "priority": "normal",
        "status": "active",
        "git_profile": "data",
        "summary": "Curated historical research, editorial articles, and cultural blog publications focusing on ancient Mesopotamian civilization (Eridu, Babylon) and Iraqi heritage.",
        "tech_stack": [
            "Markdown & Editorial Publishing Framework",
            "Historical & Archaeological Research",
            "High-Resolution Photographic Archives",
            "Automated Content Extraction Prompts",
        ],
        "objectives": [
            "Produce academically accurate, engaging articles on Mesopotamian archaeology.",
            "Highlight cultural heritage sites across southern Iraq for cultural tourism.",
            "Structure media and citations for syndication across web channels.",
        ],
        "tasks": [
            {"title": "Finalize article: Eridu - The Birthplace of Babylon and the Dawn of Civilization", "completed": True},
            {"title": "Organize archaeological photographic assets and licensing attribution", "completed": False},
            {"title": "Build publishing pipeline to export markdown articles to web CMS", "completed": False},
        ],
    },
    {
        "folder": "HotelWebsite",
        "slug": "hotel-website",
        "name": "Downtown Hotel Web Portal",
        "category": "Web & Hospitality",
        "priority": "normal",
        "status": "active",
        "git_profile": "node",
        "summary": "Full-stack hotel showcase and booking web application with comprehensive branding assets, room catalogs, and amenity highlights.",
        "tech_stack": [
            "Next.js & TypeScript (App Router)",
            "Tailwind CSS & Lama Sans Custom Typography",
            "High-Resolution Hotel Asset Processing Pipeline",
            "Downtown Hotel Comprehensive Brand Identity",
        ],
        "objectives": [
            "Showcase hotel rooms, executive suites, dining, and event facilities.",
            "Provide streamlined reservation requests and direct guest communications.",
            "Deliver fast mobile performance and bilingual (Arabic/English) presentations.",
        ],
        "tasks": [
            {"title": "Process and compress high-resolution hotel branding and room photos", "completed": True},
            {"title": "Construct interactive room showcase cards and amenity filters", "completed": False},
            {"title": "Wire reservation inquiry submission and confirmation routing", "completed": False},
        ],
    },
    {
        "folder": "LifeData",
        "slug": "life-data",
        "name": "LifeData Health & Telemetry",
        "category": "Data & Personal Analytics",
        "priority": "normal",
        "status": "active",
        "git_profile": "data",
        "summary": "Personal analytics platform processing Samsung Health exports (heart rate, pedometer, sleep stages, stress, vitality) and Google Timeline geospatial history.",
        "tech_stack": [
            "Samsung Health Export Parsing (CSV Metrics)",
            "Google Timeline Geospatial Tracking (JSON)",
            "Python Data Analytics & Aggregation",
            "Longitudinal Trend Modeling",
        ],
        "objectives": [
            "Consolidate biometric telemetry and physical activity history into unified datasets.",
            "Analyze sleep quality, daily exertion, stress response, and vitality trends over time.",
            "Derive actionable lifestyle insights and geospatial habit maps.",
        ],
        "tasks": [
            {"title": "Structure ingestion parsers for Samsung Health multi-table CSV files", "completed": False},
            {"title": "Parse and normalize Google Timeline travel segments and locations", "completed": False},
            {"title": "Generate comprehensive longitudinal vitality and recovery dashboards", "completed": False},
        ],
    },
    {
        "folder": "MaxwellEMvisual",
        "slug": "maxwell-em-visual",
        "name": "Maxwell EM Field Visualizer",
        "category": "Science & Visualization",
        "priority": "normal",
        "status": "active",
        "git_profile": "node",
        "summary": "Interactive web-based simulation and pedagogical visualization tool for Maxwell's electromagnetic equations, wave propagation, and vector field dynamics.",
        "tech_stack": [
            "Node.js & Express Web Server",
            "HTML5 Canvas & Vector Field Rendering",
            "JavaScript Numerical Physics Solvers",
            "Electrodynamics & Wave Propagation Models",
        ],
        "objectives": [
            "Provide intuitive visual representations of curl, divergence, and Maxwell's 4 equations.",
            "Simulate EM wave propagation across dielectric boundaries and varying media.",
            "Serve as an interactive educational module for electrodynamics concepts.",
        ],
        "tasks": [
            {"title": "Implement basic 2D electromagnetic wave propagation canvas", "completed": True},
            {"title": "Add interactive parameter controls for frequency, permittivity, and boundary conditions", "completed": False},
            {"title": "Extract and index theoretical course notes for in-app formula tooltips", "completed": False},
        ],
    },
    {
        "folder": "MedicalEcommerce",
        "slug": "medical-ecommerce",
        "name": "Iraqi Medical E-Commerce Research",
        "category": "Market Research & Strategy",
        "priority": "normal",
        "status": "active",
        "git_profile": "data",
        "summary": "Comprehensive feasibility study, competitor analysis, dental platform evaluations, and market entry strategy for Iraqi medical supply e-commerce.",
        "tech_stack": [
            "Market Research & Regulatory Documentation",
            "Competitive Benchmarking Matrix",
            "Iraqi Dental & Medical Supply Chain Models",
            "Technical Architecture & MVP Specifications",
        ],
        "objectives": [
            "Evaluate market demand, regulatory compliance, and payment friction for medical e-commerce in Iraq.",
            "Analyze existing dental supply platforms and identify distributor pain points.",
            "Formulate an executable MVP architecture and vendor onboarding model.",
        ],
        "tasks": [
            {"title": "Complete Iraqi Medical E-Commerce Feasibility report", "completed": True},
            {"title": "Synthesize Iraqi Dental Platforms Analysis and vendor pricing models", "completed": True},
            {"title": "Draft technical requirements and supplier payment gateway specification", "completed": False},
        ],
    },
    {
        "folder": "New_Operrations",
        "slug": "new-operations",
        "name": "Bil Weekend Operations Portal",
        "category": "Operations & Web Services",
        "priority": "high",
        "status": "active",
        "git_profile": "python",
        "summary": "Core operations backend and web management system for Bil Weekend booking management, tour scheduling, traveler logistics, and Render deployment.",
        "tech_stack": [
            "FastAPI & Python 3.11+",
            "SQLAlchemy ORM & Pydantic Validation",
            "Render Cloud Deployment Config (`render.yaml`)",
            "Pytest Automated Test Suite",
        ],
        "objectives": [
            "Centralize booking lifecycles, bus seating allocations, and tour rosters.",
            "Provide operations coordinators with real-time traveler status dashboards.",
            "Maintain robust cloud deployment on Render with automated data snapshots.",
        ],
        "tasks": [
            {"title": "Implement FastAPI booking endpoints and status state machines", "completed": True},
            {"title": "Configure Render deployment pipeline and environment secrets", "completed": True},
            {"title": "Expand automated unit and integration test coverage", "completed": False},
        ],
    },
    {
        "folder": "OdysseusWork",
        "slug": "odysseus-work",
        "name": "Odysseus Agent Platform Hub",
        "category": "AI Agent Platform",
        "priority": "critical",
        "status": "active",
        "git_profile": "python",
        "summary": "Central development hub for Odysseus: multi-agent autonomous system, browser extensions, Android widget, background schedulers, and memory store.",
        "tech_stack": [
            "Python 3, FastAPI, SQLite / SQLAlchemy",
            "ChromaDB & FastEmbed Vector Embeddings",
            "Browser Extensions (Brave/Chrome Manifest V3)",
            "Android Companion Widget & Mobile Connectors",
        ],
        "objectives": [
            "Serve as the master orchestrator for all personal and business workflows.",
            "Provide persistent multi-project workspace synchronization and living context.",
            "Execute scheduled background email, calendar, and operational agent tasks autonomously.",
        ],
        "tasks": [
            {"title": "Implement Hybrid Projects Manager with YAML frontmatter sync", "completed": True},
            {"title": "Catalog and link all 21 workspace projects into Odysseus app.db", "completed": False},
            {"title": "Monitor ambient email triage and scheduled operations dispatchers", "completed": False},
        ],
    },
    {
        "folder": "OperationsAutomationSrv",
        "slug": "operations-automation-srv",
        "name": "Operations Automation Service",
        "category": "Automation & Services",
        "priority": "high",
        "status": "active",
        "git_profile": "python",
        "summary": "Durable background worker service automating tour operations, automated notification dispatch, scheduled sync routines, and data integrity checks.",
        "tech_stack": [
            "Python 3 & Poetry Packaging",
            "Asyncio Background Cron Runners",
            "REST API Client Integrations",
            "Automated Operations Health Audits",
        ],
        "objectives": [
            "Automate repetitive operational data processing and customer communication dispatches.",
            "Detect data inconsistencies between booking sheets and operations databases.",
            "Provide fault-tolerant scheduling and logging for background workers.",
        ],
        "tasks": [
            {"title": "Configure Poetry project dependencies and runtime entry points", "completed": True},
            {"title": "Audit automated scheduled task dispatchers and error recovery", "completed": False},
            {"title": "Implement webhook listeners for external booking platform events", "completed": False},
        ],
    },
    {
        "folder": "OudProject",
        "slug": "oud-project",
        "name": "Oud Perfume Brand Research",
        "category": "Brand & Research",
        "priority": "normal",
        "status": "active",
        "git_profile": "data",
        "summary": "Brand formulation, market research, visual identity, and product packaging specifications for luxury oriental Oud and perfumery.",
        "tech_stack": [
            "Comprehensive Market & Scent Research Reports",
            "Oud Brand Logo & Visual Assets",
            "Product Packaging Technical PDF Blueprints",
            "Luxury Retail Positioning Strategy",
        ],
        "objectives": [
            "Define the luxury brand identity and visual aesthetic for authentic oriental Oud.",
            "Synthesize scent profile hierarchies, raw ingredient sourcing, and bottling specs.",
            "Formulate pricing tiers and direct-to-consumer digital marketing strategy.",
        ],
        "tasks": [
            {"title": "Synthesize comprehensive Oud Market Research Report", "completed": True},
            {"title": "Review bottle blueprint PDFs and packaging manufacturing requirements", "completed": False},
            {"title": "Finalize launch fragrance product lineup and pricing matrix", "completed": False},
        ],
    },
    {
        "folder": "Pharmacy",
        "slug": "pharmacy-digitization",
        "name": "Iraqi Pharmacy Digitization",
        "category": "Healthcare & Research",
        "priority": "normal",
        "status": "active",
        "git_profile": "data",
        "summary": "In-depth analysis of Iraq's pharmaceutical supply chain, Kimadia awarding tenders, WHO essential drug lists, and digital inventory management systems.",
        "tech_stack": [
            "WHO Essential Drugs List & Classification Data",
            "Kimadia National Drug Awarding Datasets (2026)",
            "Healthcare Market Digitization Specs",
            "Gudea Data Access Architecture",
        ],
        "objectives": [
            "Analyze national pharmaceutical supply chains, pricing distortions, and tender allocations in Iraq.",
            "Cross-reference WHO essential medicines against Kimadia tender lists.",
            "Architect a modern inventory and supply chain tracking platform for Iraqi pharmacies.",
        ],
        "tasks": [
            {"title": "Complete Iraqi Pharmacy Digitization Analysis and 2026 Market Status report", "completed": True},
            {"title": "Index Kimadia drug awarding table data and essential medicine mappings", "completed": False},
            {"title": "Specify Gudea secure data access and distribution framework", "completed": False},
        ],
    },
    {
        "folder": "Productsearch",
        "slug": "product-search",
        "name": "Product Search Engine",
        "category": "Search & Scraping",
        "priority": "normal",
        "status": "active",
        "git_profile": "python",
        "summary": "High-precision product discovery and scraping engine designed to aggregate, parse, and rank retail products across online stores.",
        "tech_stack": [
            "Python 3 Web Scrapers & Parsers",
            "Product Normalization & Deduplication Pipeline",
            "JSON Schema Search Indexing",
            "Pytest Automated Test Harness",
        ],
        "objectives": [
            "Scrape and normalize product listings across fragmented e-commerce sites.",
            "Provide fast full-text search and faceted filtering by category, price, and merchant.",
            "Track price history and stock availability fluctuations.",
        ],
        "tasks": [
            {"title": "Define core search and scraping architecture specifications in SPEC.md", "completed": True},
            {"title": "Implement retail site scrapers in `ps/` package with selector fallbacks", "completed": False},
            {"title": "Write unit tests for price parsing and unicode text extraction", "completed": False},
        ],
    },
    {
        "folder": "RehlatWebsite",
        "slug": "rehlat-website",
        "name": "Rehlat Al-Utla Travel Platform",
        "category": "Web & Travel",
        "priority": "high",
        "status": "active",
        "git_profile": "node",
        "summary": "Next.js travel discovery and booking web application presenting curated Iraqi tours, historical excursions, and cultural packages.",
        "tech_stack": [
            "Next.js (App Router) & React",
            "Tailwind CSS & PostCSS",
            "Travel Package Data Models",
            "Tour Itinerary Visual Showcase",
        ],
        "objectives": [
            "Deliver an inviting travel portal for domestic and international tourists in Iraq.",
            "Showcase multi-day tour itineraries, cultural landmarks, and package inclusions.",
            "Provide direct reservation bookings and customer inquiry forms.",
        ],
        "tasks": [
            {"title": "Build responsive tour package showcase and trip details pages", "completed": True},
            {"title": "Integrate tour booking inquiry forms and customer contact workflows", "completed": False},
            {"title": "Add interactive photo galleries and customer trip reviews", "completed": False},
        ],
    },
    {
        "folder": "SBAH_Ticketing",
        "slug": "sbah-ticketing",
        "name": "SBAH Antiquities Ticketing",
        "category": "Heritage & Revenue",
        "priority": "high",
        "status": "active",
        "git_profile": "data",
        "summary": "State Board of Antiquities and Heritage (SBAH) digital ticketing validation system, revenue tracking models, and museum visitor reconciliation.",
        "tech_stack": [
            "SBAH Financial & Revenue Reconciliation Models (Excel)",
            "Field Ticket Validation & QR Scanner Records",
            "Android Platform Tools / Scanner Deployment",
            "Visitor Attendance Audit Logs",
        ],
        "objectives": [
            "Digitize and reconcile ticket issuance across historical monuments and museums.",
            "Validate revenue intake against official government audit spreadsheets.",
            "Ensure field handheld scanners sync reliably in low-connectivity conditions.",
        ],
        "tasks": [
            {"title": "Structure SBAH revenue validation model and audit records", "completed": True},
            {"title": "Reconcile site visitor counts with issued ticket serial numbers", "completed": False},
            {"title": "Draft handheld scanner deployment and sync guidelines", "completed": False},
        ],
    },
    {
        "folder": "ServicesComaprison",
        "slug": "services-comparison",
        "name": "Iraqi Tourism Services Comparison",
        "category": "Analytics & Comparison",
        "priority": "normal",
        "status": "active",
        "git_profile": "data",
        "summary": "Comparative benchmarking dashboard and analytic reports evaluating tour operators (Alzaeem, Dar Al-Raheem, Rehlat Al-Safari) in Iraq.",
        "tech_stack": [
            "Provider Comparison Dashboards (Excel)",
            "Service Inclusion & Cost Analysis Methodology",
            "Tour Operator Spreadsheet Aggregators",
            "Comparative Market Intelligence Reports",
        ],
        "objectives": [
            "Benchmark competitive pricing, lodging tiers, and itinerary depth across providers.",
            "Identify margin opportunities and cost structures in domestic tourism.",
            "Provide clear visual dashboards comparing provider ratings and inclusions.",
        ],
        "tasks": [
            {"title": "Compile Provider Comparison Dashboard and Comparison Report", "completed": True},
            {"title": "Normalize tour pricing data across Alzaeem, Dar Al-Raheem, and Rehlat Al-Safari", "completed": False},
            {"title": "Publish recommendations on pricing strategy and unique value propositions", "completed": False},
        ],
    },
    {
        "folder": "TermuxSamsung",
        "slug": "termux-samsung",
        "name": "Termux Mobile Inference Node",
        "category": "Mobile & Edge AI",
        "priority": "high",
        "status": "active",
        "git_profile": "python",
        "summary": "Edge AI and benchmark testing infrastructure running on Samsung Android devices via Termux, handling pooled model inference and remote agent execution.",
        "tech_stack": [
            "Python & Bash / PowerShell Automation",
            "Termux Linux Runtime Environment on Android",
            "SSH Key Authentication & Persistent Daemons",
            "Local LLM Benchmark Harness (Granite, Muse, Gemini Direct)",
        ],
        "objectives": [
            "Harness Samsung device NPU/CPU compute for decentralized edge inference.",
            "Maintain persistent, self-healing SSH tunnels and background execution loops.",
            "Run continuous model throughput and accuracy benchmarks on mobile silicon.",
        ],
        "tasks": [
            {"title": "Implement benchmark scripts for pooled mobile model inference", "completed": True},
            {"title": "Harden SSH daemon keepalive and automated Termux boot scripts", "completed": False},
            {"title": "Integrate direct Gemini API fallback routing in `antigravity_direct_gemini.py`", "completed": True},
        ],
    },
    {
        "folder": "WebsiteConnection",
        "slug": "website-connection",
        "name": "Tour Itinerary & Map Studio Connector",
        "category": "Geospatial & Sync",
        "priority": "normal",
        "status": "active",
        "git_profile": "python",
        "summary": "Data transformation layer, OCR extraction (Tesseract), itinerary synchronization, and Map Studio geospatial routing for travel platforms.",
        "tech_stack": [
            "Python Data Transformation Scripts",
            "Tesseract OCR Engine (`tessdata`)",
            "Excel Sheet Parsing & Schema Hardening",
            "Map Studio Geospatial Coordinate Generator",
        ],
        "objectives": [
            "Extract unstructured tour schedules from spreadsheets and image flyers into clean JSON.",
            "Generate accurate GPS waypoint coordinates and interactive maps for itineraries.",
            "Maintain automated push synchronization with live website backends.",
        ],
        "tasks": [
            {"title": "Build itinerary layer and Map Studio coordinate generators", "completed": True},
            {"title": "Harden Excel sheet parser against irregular date formats and missing cells", "completed": False},
            {"title": "Verify Tesseract OCR Arabic text extraction on scanned itineraries", "completed": False},
        ],
    },
    {
        "folder": "weddingproject",
        "slug": "wedding-project",
        "name": "Wedding Planning Web Platform",
        "category": "Web & Events",
        "priority": "normal",
        "status": "active",
        "git_profile": "node",
        "summary": "Interactive wedding invitation, guest RSVP management, venue directions, and event schedule web application.",
        "tech_stack": [
            "Next.js & TypeScript (App Router)",
            "React 19 & Tailwind CSS",
            "Interactive RSVP State & Guest Management",
            "Venue Maps & Countdown Timers",
        ],
        "objectives": [
            "Provide guests with a beautiful digital invitation and real-time event updates.",
            "Collect and organize RSVP confirmations, dietary notes, and attendance counts.",
            "Deliver interactive maps and schedule timelines for the wedding celebration.",
        ],
        "tasks": [
            {"title": "Build Next.js web application structure and responsive UI", "completed": True},
            {"title": "Implement guest RSVP submission form and data persistence", "completed": False},
            {"title": "Embed interactive venue directions and celebratory photo showcase", "completed": False},
        ],
    },
]

GITIGNORE_PROFILES = {
    "node": "\n".join([
        "# Node.js / Next.js",
        "node_modules/",
        ".next/",
        "out/",
        "build/",
        "dist/",
        ".env.local",
        ".env.*.local",
        "*.tsbuildinfo",
        "npm-debug.log*",
        "yarn-debug.log*",
        "yarn-error.log*",
        ".DS_Store",
        "Thumbs.db",
    ]),
    "python": "\n".join([
        "# Python / FastAPI",
        "__pycache__/",
        "*.py[cod]",
        "*$py.class",
        ".pytest_cache/",
        "venv/",
        ".venv/",
        "env/",
        ".env",
        "*.log",
        ".DS_Store",
        "Thumbs.db",
    ]),
    "flutter": "\n".join([
        "# Flutter / Dart",
        ".dart_tool/",
        ".flutter-plugins",
        ".flutter-plugins-dependencies",
        ".packages",
        "build/",
        ".idea/",
        "*.iml",
        "android/local.properties",
        "ios/Flutter/Generated.xcconfig",
        "ios/Flutter/flutter_export_environment.sh",
        "node_modules/",
        ".DS_Store",
        "Thumbs.db",
    ]),
    "data": "\n".join([
        "# Data & Research",
        "*.tmp",
        "~$*",
        ".DS_Store",
        "Thumbs.db",
        "*.log",
        ".vscode/",
        ".claude/",
    ]),
}


def setup_git_and_gitignore():
    """Ensure every project has an initialized Git repo and stack-appropriate .gitignore."""
    print("\n--- PHASE 1: Git & .gitignore Provisioning ---")
    for proj in PROJECT_DEFINITIONS:
        folder_path = WORKSPACE_ROOT / proj["folder"]
        if not folder_path.exists():
            print(f"[SKIP] Folder does not exist: {folder_path}")
            continue

        # Check or create .gitignore
        gitignore_path = folder_path / ".gitignore"
        if not gitignore_path.exists():
            profile = proj.get("git_profile", "data")
            content = GITIGNORE_PROFILES.get(profile, GITIGNORE_PROFILES["data"])
            gitignore_path.write_text(content, encoding="utf-8")
            print(f"[GITIGNORE] Created .gitignore for {proj['folder']} (Profile: {profile})")
        else:
            print(f"[GITIGNORE] Existing .gitignore found for {proj['folder']}")

        # Check or initialize Git
        git_dir = folder_path / ".git"
        if not git_dir.exists():
            try:
                res = subprocess.run(
                    ["git", "init"],
                    cwd=str(folder_path),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                print(f"[GIT INIT] Initialized Git repo in {proj['folder']}: {res.stdout.strip()}")
            except Exception as e:
                print(f"[ERROR] Failed git init in {proj['folder']}: {e}")
        else:
            print(f"[GIT] Repository already active in {proj['folder']}")


def generate_project_manifests():
    """Create a standardized PROJECT.md in every project's root folder."""
    print("\n--- PHASE 2: Generating PROJECT.md Manifests ---")
    now_iso = datetime.now(timezone.utc).isoformat()

    for proj in PROJECT_DEFINITIONS:
        folder_path = WORKSPACE_ROOT / proj["folder"]
        if not folder_path.exists():
            continue

        manifest_path = folder_path / "PROJECT.md"
        proj_id = f"proj_{uuid.uuid4().hex[:8]}"

        # Frontmatter metadata
        metadata = {
            "id": proj_id,
            "name": proj["name"],
            "slug": proj["slug"],
            "status": proj["status"],
            "priority": proj["priority"],
            "owner": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "links": [],
        }

        # Format body
        tech_stack_md = "\n".join([f"- **{t}**" for t in proj["tech_stack"]])
        objectives_md = "\n".join([f"- {o}" for o in proj["objectives"]])
        tasks_md = "\n".join([
            f"- [{'x' if t['completed'] else ' '}] {t['title']}"
            for t in proj["tasks"]
        ])

        body = (
            f"# {proj['name']}\n\n"
            f"{proj['summary']}\n\n"
            f"## Architecture & Tech Stack\n"
            f"- **Domain Category**: {proj['category']}\n"
            f"- **Source Folder**: `{folder_path}`\n"
            f"{tech_stack_md}\n\n"
            f"## Objectives\n"
            f"{objectives_md}\n\n"
            f"## Active Tasks\n"
            f"{tasks_md}\n\n"
            f"## Execution Log\n"
            f"- *{now_iso} (System)*: Project cataloged and linked into Odysseus agent platform.\n"
        )

        manifest_content = serialize_project_manifest(metadata, body)
        manifest_path.write_text(manifest_content, encoding="utf-8")
        print(f"[MANIFEST] Generated: {manifest_path}")


def populate_odysseus_database():
    """Register all 21 projects and their parsed tasks into Odysseus app.db."""
    print("\n--- PHASE 3: Populating Odysseus app.db ---")
    db = SessionLocal()
    try:
        for proj in PROJECT_DEFINITIONS:
            folder_path = WORKSPACE_ROOT / proj["folder"]
            manifest_path = folder_path / "PROJECT.md"
            if not manifest_path.exists():
                print(f"[SKIP DB] Manifest missing for {proj['folder']}")
                continue

            manifest_content = manifest_path.read_text(encoding="utf-8")
            parsed_tasks = parse_tasks_from_markdown(manifest_content)

            task_total = len(parsed_tasks)
            task_completed = sum(1 for t in parsed_tasks if t.get("completed"))

            # Check if project already exists by slug
            existing = db.query(Project).filter(Project.slug == proj["slug"]).first()
            if existing:
                existing.name = proj["name"]
                existing.description = proj["summary"]
                existing.status = proj["status"]
                existing.priority = proj["priority"]
                existing.folder_path = str(folder_path)
                existing.manifest_path = str(manifest_path)
                existing.task_total = task_total
                existing.task_completed = task_completed
                proj_id = existing.id
                print(f"[DB UPDATE] Updated project: {proj['slug']} ({proj_id})")
            else:
                proj_id = f"proj_{uuid.uuid4().hex[:8]}"
                new_project = Project(
                    id=proj_id,
                    slug=proj["slug"],
                    name=proj["name"],
                    description=proj["summary"],
                    status=proj["status"],
                    priority=proj["priority"],
                    owner="default",
                    folder_path=str(folder_path),
                    manifest_path=str(manifest_path),
                    task_total=task_total,
                    task_completed=task_completed,
                )
                db.add(new_project)
                print(f"[DB INSERT] Inserted project: {proj['slug']} ({proj_id})")

            # Refresh tasks
            db.query(ProjectTask).filter(ProjectTask.project_id == proj_id).delete()
            for t in parsed_tasks:
                task_record = ProjectTask(
                    id=f"ptask_{uuid.uuid4().hex[:8]}",
                    project_id=proj_id,
                    title=t["title"],
                    completed=t["completed"],
                    sort_order=t["sort_order"],
                )
                db.add(task_record)

        db.commit()
        print(f"[DB SUCCESS] All {len(PROJECT_DEFINITIONS)} projects and tasks committed to SQLite.")
    finally:
        db.close()


def create_filesystem_junctions():
    """Create NTFS junctions in Odysseus data/projects/<slug> pointing to project roots."""
    print("\n--- PHASE 4: Creating Filesystem Junctions ---")
    ODYSSEUS_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    for proj in PROJECT_DEFINITIONS:
        folder_path = WORKSPACE_ROOT / proj["folder"]
        junction_path = ODYSSEUS_PROJECTS_DIR / proj["slug"]

        if not folder_path.exists():
            continue

        if junction_path.exists():
            print(f"[EXISTS] Link/Folder already present: {junction_path}")
            continue

        try:
            cmd = f'cmd /c mklink /J "{junction_path}" "{folder_path}"'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if res.returncode == 0:
                print(f"[JUNCTION] Linked {proj['slug']} -> {folder_path}")
            else:
                print(f"[JUNCTION WARN] mklink output: {res.stderr.strip() or res.stdout.strip()}")
        except Exception as e:
            print(f"[JUNCTION ERROR] Could not link {proj['slug']}: {e}")


def verify_installation():
    """Verify database and filesystem state."""
    print("\n--- PHASE 5: Verification & Diagnostics ---")
    db = SessionLocal()
    try:
        projs = db.query(Project).all()
        tasks = db.query(ProjectTask).all()
        print(f"\n[SUMMARY] Total Projects in Odysseus: {len(projs)}")
        print(f"[SUMMARY] Total Project Tasks: {len(tasks)}")
        print("\n" + "=" * 80)
        print(f"{'SLUG':<25} | {'NAME':<35} | {'TASKS':<8} | {'STATUS'}")
        print("=" * 80)
        for p in projs:
            print(f"{p.slug:<25} | {p.name[:35]:<35} | {p.task_completed}/{p.task_total:<6} | {p.status}")
        print("=" * 80)
    finally:
        db.close()


if __name__ == "__main__":
    setup_git_and_gitignore()
    generate_project_manifests()
    populate_odysseus_database()
    create_filesystem_junctions()
    verify_installation()
