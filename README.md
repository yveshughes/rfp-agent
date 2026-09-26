# RFP Agent

An always-on agent, working on your behalf to win RFP opportunities. This repository contains the product pitch and technical overview.

Built for the Vultr Agent Arena Hackathon 2026 · Future of Work.

## Current status

This repository contains the **pitch page and technical overview only**. The application, AI processing, voice editing, and NetBird integration are not implemented yet. The page illustrates the intended workflow; it is not an interactive application screenshot.

The “Live Demo” link opens `/app/` in a new tab. That route is a static workspace entry page, not a functioning application. Replace the demo links when the application is ready. Public pages omit temporary development banners; that does not change the implementation status documented here.

The 6,222 figure is the size of the source directory collected for this project. It does not describe verified portals, active RFPs, or completed agent searches. The raw directory and research documents are not distributed in this repository.

## Preview locally

No build step or dependency installation is required:

```sh
python3 -m http.server 8080 --directory site
```

Open http://localhost:8080. The technical overview lives at `/technical/`. Fonts are requested from Google Fonts, with system fallbacks. The technical page loads pinned Mermaid 12.0.0 from jsDelivr and renders `site/assets/workflow.mmd`; the written workflow remains available if the diagram cannot load. The decorative hero video has a pause control and respects reduced-motion preferences.

## Deploy on Vultr

Use a small Ubuntu or Debian VM. Copy or clone this repository onto it and run:

```sh
sudo sh deploy/install.sh
```

The installer serves **only `site/`** through nginx. Repository files, planning materials, and credentials are never copied into the web root. Allow HTTP ingress for this public preview; configure HTTPS with your domain before adding application accounts or uploading documents. The eventual application can use a separate NetBird-protected service.

## Repository boundaries

The root `.gitignore` allows only `site/`, `deploy/`, this README, the license, and the ignore file. Local plans, presentation scripts, recordings, research, datasets, and temporary files remain outside version control. Audit the staged file list before every publication.

## Assets and license

Code: MIT. The decorative hero animation was generated with Higgsfield / Seedance 2.0 for this project and optimized for web playback. It is an illustration of the product vision, not evidence of an actual contract award. The GitHub mark comes from Primer Octicons; its MIT notice is included in `site/assets/github-LICENSE.txt`. No endorsement or affiliation with any example proposal owner is implied.
