# Submission Checklist

Student: **Ritesh Kumar** (ID **3217327**). NAGP AWS Cloud Computing & Network Security
case study — insurance document-upload MVP.

| Requirement | Status | Evidence / Location |
|-------------|--------|---------------------|
| Architecture diagram | Done | `Architecture.png`, `docs/architecture.svg`, `docs/architecture.mmd` |
| Component description | Done | `NAGP_AWS_Component_Description.pdf`, `docs/COMPONENTS.md` |
| VPC / two-AZ design | Done | `infra/foundation.yaml`; `docs/COMPONENTS.md` |
| Public / app / DB subnet tiers | Done | Six /24 subnets across two AZs — `infra/foundation.yaml` |
| Internet Gateway | Done | `infra/foundation.yaml` (public route only) |
| NAT design decision | Done | Not deployed (endpoints instead) — `docs/SCOPE_AND_ASSUMPTIONS.md`, diagram |
| Application Load Balancer | Done | Internet-facing HTTP:80 — `infra/application.yaml` |
| EC2 application tier | Done | Private t3.micro, Python 3.11/Flask/Gunicorn — `app/`, `infra/` |
| Auto Scaling Group | Done | min 2 / desired 2 / max 4 + target-tracking — `infra/application.yaml` |
| Security groups | Done | ALB→app:8000, Lambda→RDS:3306 only — `docs/SECURITY_DESIGN.md` |
| Network ACLs | Done | Public/app/DB tiers (Lambda TCP+UDP ephemeral) — `infra/foundation.yaml` |
| IAM users/groups + roles | Done | `nagp-developers`/`nagp-developer`; EC2/Lambda/Builder roles — `infra/`, `docs/SECURITY_DESIGN.md` |
| Private S3 storage | Done | BPA, SSE-S3, TLS-only — `infra/foundation.yaml` |
| S3 upload event | Done | `uploads/` `ObjectCreated` → Lambda — `infra/foundation.yaml` |
| Python Lambda (boto3) | Done | Python 3.14, PyMySQL — `lambda_src/handler.py` |
| Private RDS (MySQL) | Done | db.t3.micro, Single-AZ, private, encrypted — `infra/application.yaml` |
| RDS reachable only from Lambda | Done | RDS SG inbound 3306 = Lambda SG only |
| Secrets Manager (bonus) | Done | RDS-managed credentials; no password in code/env |
| Private VPC endpoints (bonus) | Done | S3 Gateway + Secrets Manager + CloudWatch Logs interface endpoints |
| CloudWatch logs | Done | Lambda log group via Logs interface endpoint |
| CloudWatch dashboard (bonus) | Done | `nagp-overview` — `infra/application.yaml` |
| CloudWatch alarms (bonus) | Done | Six explicit alarms — `infra/application.yaml` |
| Source code | Done | `app/`, `lambda_src/`, `tests/` |
| CloudFormation (IaC) | Done | `infra/foundation.yaml`, `infra/builder.yaml`, `infra/application.yaml` |
| Dependencies | Done | `app/requirements.txt`, `lambda_src/requirements.txt`, `requirements-dev.txt` |
| Deployment instructions | Done | `docs/DEPLOYMENT.md`, `infra/README.md` |
| Scope / assumptions | Done | `docs/SCOPE_AND_ASSUMPTIONS.md` |
| Validation evidence | Done | `docs/VALIDATION.md` |
| Cleanup / cost | Done | `docs/COST_AND_CLEANUP.md` (teardown verified) |
| Requirements traceability | Done | `docs/REQUIREMENTS_TRACEABILITY.md` |
| Functional demo video (≤ 2 min) | Submitted separately | Not in this repository |
| AWS configuration walkthrough video (≤ 8 min) | Submitted separately | Not in this repository |

The two demonstration videos are submitted separately and are intentionally not included in
this repository.
