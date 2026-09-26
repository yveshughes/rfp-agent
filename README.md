# RFP Agent

An always-on agent, working on your behalf to win RFP opportunities. This repository contains the product pitch and technical overview.

Built for the Vultr Agent Arena Hackathon 2026 · Future of Work.

## Current status

The pitch and technical reference are publicly hosted on Vultr. The first **Billy workspace** now includes the five-section UI, all-source lookup, a real Chromium session with watch/take-control controls, PDF page-range import, saved research, activity and approval handling. Its private API and browser run on Vultr, reached from the Mac through an SSH tunnel. See [app setup and limitations](app/README.md).

Open-ended model chat, semantic evidence matching, proposal generation, voice revision and NetBird integration are not connected yet. The public `/app/` entry remains separate from the locally connected workspace until authenticated public ingress is ready. Source lookup uses actual directory records; the animation is decorative and does not indicate a completed agent action.

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

## Technical decision record

The technical page’s **Key decisions** section (`/technical/#decisions`) records deployed choices, rationale, tradeoffs and verification evidence for technical Q&A. Update it when hosting, access, persistence, model-provider or deployment decisions change. Keep completed infrastructure separate from planned agent capabilities, and exclude credentials and billing details.

## Repository boundaries

The root `.gitignore` allows only `site/`, `app/`, `tests/`, `deploy/`, this README, the license, and the ignore file. Local plans, presentation scripts, recordings, research, datasets, and temporary files remain outside version control. Audit the staged file list before every publication.

## Assets and license

Code: MIT. The decorative hero animation was generated with Higgsfield / Seedance 2.0 for this project and optimized for web playback. It is an illustration of the product vision, not evidence of an actual contract award. The GitHub mark comes from Primer Octicons; its MIT notice is included in `site/assets/github-LICENSE.txt`. No endorsement or affiliation with any example proposal owner is implied.
