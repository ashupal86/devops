# social-links

A tiny "link in bio" app. Pick a tag (e.g. `@ada`), write a short message, add links to your socials, and share one URL: `https://<host>/ada`.

- **backend/**: FastAPI + SQLAlchemy (SQLite by default, Postgres via `DATABASE_URL`)
- **frontend/**: React + Vite + TypeScript, React Router

## How editing works (no accounts)

When you create a profile, the API returns a random **edit key** once. The server stores only its SHA-256 hash. The browser keeps the key in `localStorage` so the owner can edit later. On another device, paste the key on `/<tag>/edit`. Updates and deletes need the `X-Edit-Token` header.

## Run locally

```bash
# API on :8000
cd backend
uv sync
uv run uvicorn app.main:app --reload

# Web on :5173 (proxies /api to :8000)
cd frontend
npm install
npm run dev
```

## Tests

```bash
cd backend  && uv run pytest --cov=app      # 53 tests
cd frontend && npm test                     # 45 tests (Vitest + Testing Library)
cd frontend && npm run build                # typecheck + production build
```

## API

| Method | Path | Auth | Notes |
|---|---|---|---|
| `POST` | `/api/profiles` | none | `201` → `{profile, edit_token}`; `409` if tag taken |
| `GET` | `/api/profiles/{tag}` | none | case-insensitive |
| `GET` | `/api/profiles/{tag}/available` | none | `{tag, available, reason}` |
| `PUT` | `/api/profiles/{tag}` | `X-Edit-Token` | replaces name/message/links (tag is immutable) |
| `DELETE` | `/api/profiles/{tag}` | `X-Edit-Token` | `204` |
| `GET` | `/api/health` | none | liveness |
| `GET` | `/api/ready` | none | readiness (checks DB), `503` if DB is down |

Interactive docs: `http://localhost:8000/docs`.

**Validation:** tags are 3–30 chars of `a-z 0-9 - _`, stored lowercase, and some words are reserved (`api`, `edit`, …). Names can be up to 80 chars, messages up to 500, and a profile can have up to 20 links. Links must be absolute `http(s)` URLs, so `javascript:` URLs are rejected by the API and never rendered by the UI.

## Configuration

| Var | Where | Default |
|---|---|---|
| `DATABASE_URL` | backend | `sqlite:///./social_links.db` (e.g. `postgresql+psycopg://user:pass@host/db`, install with `uv sync --extra postgres`) |
| `CORS_ORIGINS` | backend | `http://localhost:5173,http://127.0.0.1:5173` |
| `VITE_API_URL` | frontend build | empty (same origin, `/api`) |
| `API_PROXY_TARGET` | frontend dev | `http://127.0.0.1:8000` |

## Deploy to AWS (EKS + RDS)

Needs `terraform`, `aws`, `kubectl` and `docker`, with AWS credentials loaded (e.g. `export AWS_PROFILE=...` after `aws sso login`).

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # first time only
terraform init && terraform apply              # ~15-20 min: VPC, EKS (2 nodes), RDS, ECR, LB controller
../scripts/deploy.sh                           # build + push images, apply k8s/production.yaml, print the URL
../scripts/destroy.sh                          # delete the load balancer, then everything else
```

Terraform writes `DATABASE_URL` for the RDS instance into the `backend-database` secret, so the backend always uses that database. The stack costs roughly $0.21/hour (about $5/day) in `ap-south-1`, so destroy it when you finish testing.

## Known gaps

- Tables are created on startup (`create_all`). Use Alembic migrations before running more than one environment.
- No rate limiting on profile creation or tag checks.
- A lost edit key can't be recovered. There are no accounts or email.
