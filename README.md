# FDE Accelerated Onboarding

This repository tracks projects and exercises completed during the FDE (Field/Developer Engineer) accelerated 2-week onboarding program.

## Structure

```
fde-onboarding/
├── day-1/
│   ├── project-1-folder-stats/         # CLI tool for folder analysis
│   └── project-2-plivo-health-checker/ # Plivo account health checker
├── day-2/
│   └── project-1-flask-webhook-server/ # Flask server with ngrok webhook testing
└── FDE Accelerated Onboarding - 2 Week Plan.docx
```

## Onboarding Plan

See [`FDE Accelerated Onboarding - 2 Week Plan.docx`](./FDE%20Accelerated%20Onboarding%20-%202%20Week%20Plan.docx) for the full onboarding schedule.

## Projects

### Day 1
| # | Project | Description | Stack |
|---|---------|-------------|-------|
| 1 | [Folder Stats CLI](./day-1/project-1-folder-stats/) | CLI tool to analyze folder size, file counts, and type breakdown | Python |
| 2 | [Plivo Health Checker](./day-1/project-2-plivo-health-checker/) | Check Plivo account balance and last 10 messages | Python, Plivo SDK |

### Day 2
| # | Project | Description | Stack |
|---|---------|-------------|-------|
| 1 | [Flask Webhook Server](./day-2/project-1-flask-webhook-server/) | Flask server with `/health` and `/webhook-test` endpoints, exposed via ngrok | Python, Flask, ngrok |
| 2 | [PostgreSQL Call Log](./day-2/project-2-postgres-calllog/) | REST API to log and retrieve call records backed by PostgreSQL | Python, Flask, SQLAlchemy, PostgreSQL |

## Getting Started

```bash
git clone https://github.com/samarthbiradar-dev/fde-onboarding.git
cd fde-onboarding
```

Each project folder contains its own `README.md` with setup and usage instructions.
