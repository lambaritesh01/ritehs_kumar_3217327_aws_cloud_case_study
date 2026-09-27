# DECISIONS

Confirmed project and architecture decisions for the insurance document-upload MVP.
Design details live in `ARCHITECTURE.md`, `SECURITY_DESIGN.md`,
`IMPLEMENTATION_PLAN.md`, `COST_AND_CLEANUP.md`, and `DEMO_PLAN.md`.

## Project decisions
| # | Decision | Value |
|---|----------|-------|
| 1 | AWS region | `us-east-1` |
| 2 | Scope | All mandatory + all listed bonus requirements |
| 3 | Language | Python (Flask web app; boto3 + PyMySQL Lambda) |
| 4 | Infrastructure as Code | CloudFormation (two stacks + an ephemeral AMI builder step) |
| 5 | Cleanup | Full teardown of every provisioned resource is a graded requirement |

## Architecture decisions (validated read-only in us-east-1)
| # | Decision | Value |
|---|----------|-------|
| D1 | AZs | us-east-1a (`use1-az1`), us-east-1b (`use1-az2`) |
| D2 | VPC CIDR | 10.20.0.0/16 |
| D3 | Subnets | public 10.20.0.0/24, 10.20.1.0/24; app 10.20.10.0/24, 10.20.11.0/24; db 10.20.20.0/24, 10.20.21.0/24 (non-overlapping) |
| D4 | EC2 type | t3.micro (2 vCPU, x86_64; offered in 1a/1b; Free-plan eligible on this account); CPU credits = standard (never Unlimited); builder also t3.micro |
| D5 | Base AMI | SSM parameter `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` (resolve at deploy) |
| D6 | RDS engine | MySQL 8.0.x (candidate 8.0.42+) |
| D7 | RDS class/storage/AZ | db.t3.micro, 20 GiB gp2, Single-AZ (actual); DB subnet group spans both DB subnets (Multi-AZ-ready); RDS-managed master password in Secrets Manager |
| D8 | NAT Gateway | Not deployed (shown conceptually); VPC endpoints + custom AMI remove the need |
| D9 | VPC endpoints | S3 Gateway; Secrets Manager Interface; CloudWatch Logs Interface (all in 1a/1b) |
| D10 | App port | 8000 (Gunicorn) behind ALB HTTP:80 |
| D11 | ASG | min 2 / desired 2 / **max 4 (live)**; `AsgMaxSize` parameter (2 or 4) — 4 chosen because the Standard EC2 vCPU quota (8) supports four t3.micro; target-tracking on average CPU (50%) |
| D12 | Interface-endpoint bonus | Secrets Manager interface endpoint (PrivateLink) is the designated bonus item |
| D13 | IAM identity separation | An administrative deploy identity separate from a least-privilege application identity (`nagp-app-deployers` group + `nagp-deployer` user) |
| D14 | DB access path | RDS reachable only from the Lambda security group on 3306; the web tier has no database access |

## Resolved constraints & limitations
- **EC2 instance type = t3.micro (Free-plan eligible):** this account's AWS Free plan
  rejects t2.micro (not Free-Tier eligible), so builder and application use x86_64
  **t3.micro** (2 vCPU, standard credits). The Standard EC2 vCPU quota is **8**, so up to
  four t3.micro (8 vCPU) fit. The **live ASG is min 2 / desired 2 / max 4** — steady
  state two instances (one per AZ) with genuine scale-out headroom to four. The
  `AsgMaxSize` parameter selects 2 (constrained account, quota 5) or 4 (this deployment).
  No quota-increase request was made.
- **RDS is Single-AZ (actual):** the DB subnet group spans both AZs (Multi-AZ-ready) and
  production would enable Multi-AZ, but the actual deployment stays Single-AZ under
  Free-plan/Free-Tier constraints (no paid upgrade for the assignment). Accurate wording:
  a multi-AZ highly available application tier with a documented database HA limitation —
  the stack as a whole is not "fully highly available."
- **Lambda concurrency = 10** on a new account: sufficient for the demo.
- **Public app is HTTP:80 only:** the assignment requires public HTTP access; TLS/HTTPS on
  the ALB (ACM certificate + domain) is out of scope and documented as a limitation.

No design blockers remain before infrastructure implementation.

## Change log
- **Architecture design:** read-only us-east-1 discovery (AZs, instance-type offerings,
  AL2023 AMI, MySQL engine versions/classes, VPC endpoint services, service quotas);
  produced the design documents and decisions D1–D14.
- **Design freeze:** finalized the compute/DB sizing (later corrected to t3.micro — see
  the Free-plan entry below), Single-AZ RDS on a Multi-AZ-ready subnet group, S3 prefixes
  (`artifacts/app/`, `artifacts/lambda/`, `uploads/`) with the S3 event on `uploads/`
  only, RDS-managed master password, and the assignment traceability matrix.
- **Application & Lambda implementation:** Flask upload web tier, Python Lambda metadata
  processor (S3 event + controlled read modes), unit tests, and artifact builders.
- **Free-plan instance-type correction:** the account's AWS Free plan rejected t2.micro
  as not Free-Tier eligible, so builder and application EC2 were changed to **t3.micro**
  (Free-plan eligible, 2 vCPU, standard credits). The `AsgMaxSize` parameter (2 or 4)
  selects the maximum; the live ASG runs min 2 / desired 2 / max 4 on the 8-vCPU quota.
- **EC2 application runtime = Python 3.11:** the pinned dependencies require Python ≥ 3.10
  (e.g. `boto3==1.43.103` → Requires-Python ≥ 3.10), but the AL2023 system interpreter is
  Python 3.9. The builder installs `python3.11`/`python3.11-pip` and builds the app venv
  with Python 3.11; the AL2023 system `python3` symlink is left untouched. Lambda
  independently uses the `python3.14` managed runtime; local development is unchanged.
