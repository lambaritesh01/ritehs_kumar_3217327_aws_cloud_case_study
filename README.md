# NAGP AWS Cloud Case Study

**Student:** Ritesh Kumar &nbsp;|&nbsp; **Student ID:** 3217327
**Assignment:** Cloud Computing & Network Security — insurance document-upload MVP on AWS (us-east-1)

An insurance document-upload MVP: a Flask web tier behind a public Application Load
Balancer stores uploads in a private S3 bucket, and an S3 `ObjectCreated` event triggers a
Python Lambda that records file metadata in a private RDS MySQL database. Compute and data
tiers are private; only the ALB is internet-facing, and only the Lambda can reach the
database.

## Reviewer quick links
- **Architecture diagram:** [`Architecture.png`](Architecture.png) (source: [`docs/architecture.svg`](docs/architecture.svg), [`docs/architecture.mmd`](docs/architecture.mmd))
- **Component description (PDF):** [`NAGP_AWS_Component_Description.pdf`](NAGP_AWS_Component_Description.pdf) (also [`docs/COMPONENTS.md`](docs/COMPONENTS.md))
- **Requirements mapping:** [`SUBMISSION_CHECKLIST.md`](SUBMISSION_CHECKLIST.md), [`docs/REQUIREMENTS_TRACEABILITY.md`](docs/REQUIREMENTS_TRACEABILITY.md)
- **Deployment guide:** [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- **Validation evidence:** [`docs/VALIDATION.md`](docs/VALIDATION.md)
- **Security design:** [`docs/SECURITY_DESIGN.md`](docs/SECURITY_DESIGN.md)
- **Scope & assumptions:** [`docs/SCOPE_AND_ASSUMPTIONS.md`](docs/SCOPE_AND_ASSUMPTIONS.md)
- **Cost & cleanup:** [`docs/COST_AND_CLEANUP.md`](docs/COST_AND_CLEANUP.md)

> **Demonstration videos are submitted separately** (not in this repository): a functional
> demo (≤ 2 minutes) and an AWS configuration walkthrough (≤ 8 minutes).

## Application flow
```
Browser --HTTP:80--> ALB --> EC2 (Flask/Gunicorn :8000) --> S3 uploads/
S3 uploads/ (ObjectCreated) --> Lambda --> Secrets Manager --> RDS MySQL
```
The EC2 web tier never connects to the database; only the Lambda does (enforced by the RDS
security group). A controlled `read_recent` Lambda mode returns recent rows to prove the
end-to-end path without exposing the database.

## Repository structure
| Path | Contents |
|------|----------|
| `app/` | Flask web application (`/`, `/health`, `POST /upload`) |
| `lambda_src/` | Python Lambda processor (S3 event + `read_recent`) |
| `infra/` | CloudFormation: `foundation.yaml`, `builder.yaml`, `application.yaml` |
| `tests/` | Unit tests (Flask + Lambda), no live AWS |
| `scripts/` | Build and test scripts |
| `docs/` | Architecture, components, deployment, validation, security, and demo docs |

## Local validation
```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\scripts\Test-Local.ps1            # 33 unit tests + syntax checks
.\scripts\Test-Infrastructure.ps1   # cfn-lint + template safety checks
.\scripts\Build-Artifacts.ps1       # app.zip + lambda.zip
```

## Deployment
Three stacks in order (foundation → builder → custom AMI → application → foundation
notification update). Commands and parameters: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
Capabilities: foundation `CAPABILITY_NAMED_IAM`, application `CAPABILITY_IAM`.

## Key design facts
- Region **us-east-1**; VPC **10.20.0.0/16**; six subnets across two AZs.
- EC2 **t3.micro** (Python 3.11) app; ASG **min 2 / desired 2 / max 4**; ALB **HTTP:80** → app **:8000** (`/health`).
- Lambda **Python 3.14**; RDS **MySQL 8.0** `db.t3.micro`, 20 GiB, **Single-AZ**, private, encrypted.
- Private endpoints: **S3 Gateway**, **Secrets Manager Interface**, **CloudWatch Logs Interface**; **NAT not deployed**.
- Bonus: **Secrets Manager**, **VPC endpoints**, **CloudWatch dashboard**, **CloudWatch alarms**.

## Demonstrated result
End-to-end upload → S3 → Lambda → Secrets Manager → RDS was validated with a controlled
test file; the metadata row was confirmed via `read_recent`. All AWS resources were then
torn down (see [`docs/VALIDATION.md`](docs/VALIDATION.md) and
[`docs/COST_AND_CLEANUP.md`](docs/COST_AND_CLEANUP.md)).

## Secrets policy
No secret (AWS keys, tokens, passwords, DB passwords, private certificates) is committed to
this repository. The web app takes no database or secret configuration; the Lambda reads
the database password only at runtime from Secrets Manager.
