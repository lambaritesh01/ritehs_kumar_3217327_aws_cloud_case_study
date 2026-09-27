# IMPLEMENTATION PLAN — NAGP AWS MVP

> **Design frozen. Nothing is deployed.** Preferred IaC: **CloudFormation** (two stacks +
> an ephemeral builder step) for reproducibility, clean teardown, and source-delivery
> evidence.

## 1. Validated capability summary (read-only discovery, us-east-1)
| Item | Result |
|------|--------|
| AZs selected | us-east-1a (`use1-az1`), us-east-1b (`use1-az2`) |
| EC2 type | **t3.micro** (2 vCPU, 1024 MiB, x86_64); Free-plan eligible; offered in 1a & 1b (validated) |
| CPU credits | **standard** (never Unlimited — avoids surplus-credit charges) |
| Base AMI | SSM param `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` (→ `ami-0fef201115eefe936`, x86_64/hvm/available; resolve fresh at deploy) |
| RDS engine | **MySQL 8.0.x** (latest 8.0.46; candidate 8.0.42+) |
| RDS class | **db.t3.micro**, gp2, AZs 1a/1b |
| RDS storage | 20 GiB gp2 |
| RDS deployment | **Single-AZ** (actual); subnet group Multi-AZ-ready |
| Endpoints | S3 **Gateway**; Secrets Manager **Interface**; Logs **Interface** — all in 1a/1b |
| Quota: EC2 Standard vCPU | **8 (applied)** |
| Quota: VPCs/region | 5 · Interface EPs/VPC 50 · ALB/region 50 · RDS instances 40 |
| Quota: Lambda concurrency | 10 (new-account; fine for demo) |

### vCPU budget (t3.micro = 2 vCPU, quota = 8)
| Phase | Instances | vCPU | Fits ≤8? |
|-------|-----------|------|---------|
| Builder alone | 1 builder | 2 | ✅ |
| Runtime ASG desired 2 | 2 app | 4 | ✅ |
| ASG scale-out to max 4 | 4 app | 8 | ✅ |

**Live ASG is min 2 / desired 2 / max 4**: steady state two instances (one per AZ) with
scale-out headroom to four (8 vCPU) within the quota. The `AsgMaxSize` parameter selects
2 (constrained account, quota 5) or 4 (this deployment). **No quota-increase request was
made.** The builder is terminated before the ASG is created.

## 2. Stack decomposition
Implemented as `infra/foundation.yaml`, `infra/builder.yaml`, `infra/application.yaml`
(deployment/teardown order and required capabilities — `CAPABILITY_NAMED_IAM` for
foundation, `CAPABILITY_IAM` for application — in `infra/README.md`).

1. **Foundation / network stack** — VPC, 6 subnets, IGW, 3 route tables + associations, S3
   Gateway Endpoint, Secrets Manager + Logs Interface Endpoints (+ `sg-vpce`), all SGs
   (`sg-alb`, `sg-ec2-app`, `sg-lambda`, `sg-rds`, `sg-builder`), NACLs (with the Lambda
   TCP+UDP ephemeral rules), DB subnet group (spans DB A/B). Exports IDs.
2. **Builder step (between stacks)** — temporary **t3.micro** in Public A: user-data
   bootstrap → fetch app from `s3://<bucket>/artifacts/app/` → build → signal → create AMI
   → **terminate builder**. AMI ID feeds the workload stack as a parameter.
3. **Workload / application stack** — S3 bucket (`artifacts/app/`, `artifacts/lambda/`,
   `uploads/`; BPA; SSE; **ObjectCreated notification on `uploads/` only**), RDS MySQL 8.0
   `db.t3.micro` 20 GiB **Single-AZ** with **`ManageMasterUserPassword=true`** (RDS-managed
   secret), IAM roles (`role-builder`, `role-ec2-app`, `role-lambda-proc`) + instance
   profiles, Launch Template (custom AMI, **t3.micro**, **standard** credits, `sg-ec2-app`,
   instance profile), Target Group + ALB + listener (80), ASG (min2/desired2/max4;
   `AsgMaxSize` supports 4) +
   target-tracking, Lambda (VPC-attached, `sg-lambda`, **PyMySQL** in package) + S3 event
   permission/source, CloudWatch dashboard + alarms.

## 3. Deployment order (dependency-aware)
1. Deploy **foundation** stack; confirm endpoints `available`.
2. Upload app + Lambda artifacts to `artifacts/app/` and `artifacts/lambda/`.
3. Run **builder**: launch t3.micro → user-data installs the **Python 3.11** runtime and a
   venv with Flask/Gunicorn/boto3 (**no PyMySQL on EC2**; system `python3` untouched) +
   systemd + `/health` → fetch artifact from S3 → signal complete →
   `create-image` (wait `available`) → **terminate builder**.
4. Deploy **workload** stack with the new AMI ID:
   a. RDS (longest) with `ManageMasterUserPassword=true` → RDS-managed secret created.
   b. IAM roles, Launch Template.
   c. Target Group, ALB, listener.
   d. ASG (launches 2 instances from the AMI, one per AZ).
   e. S3 bucket + Lambda + `uploads/` event notification (grant S3
      `lambda:InvokeFunction` before wiring).
   f. CloudWatch dashboard + alarms.
5. Validate health, run the demo, capture evidence, then tear down (`COST_AND_CLEANUP.md`).

## 4. Application & Lambda
- **Web (EC2 AMI):** Python 3 + Flask + Gunicorn (`:8000`) + boto3. **No PyMySQL** (EC2
  never touches the DB). Endpoints: `GET /health`, `GET /` (upload form), `POST /upload` →
  `s3://<bucket>/uploads/<filename>`.
- **Lambda package:** Python + boto3 + **PyMySQL**; VPC-attached; handlers for (a) S3
  ObjectCreated processing and (b) `{"action":"read_recent"}` demo read. DB credentials via
  Secrets Manager at runtime.
- **Runtime config w/o AMI rebuild:** non-secret values (bucket, region, port) via Launch
  Template user-data / instance tags / SSM Parameter Store (non-secret). Secrets never on
  EC2.

## 5. Bonus design (all mandatory for us)
### 5.1 Secrets Manager — RDS-managed master credentials (preferred)
- Use **`ManageMasterUserPassword=true`** on the RDS instance so **RDS creates and manages
  (and can rotate) the master-user secret** in Secrets Manager. The Lambda references the
  **resulting secret ARN** (exposed as a stack output / resolved attribute) and calls
  `GetSecretValue` through the Secrets Manager **interface endpoint**. **No password ever
  appears** in source code, CloudFormation parameters, Git, user-data, or environment docs.
- **CFN support to confirm at implementation:** `AWS::RDS::DBInstance` supports
  `ManageMasterUserPassword` and exposes `MasterUserSecret.SecretArn`. Validate read-only
  before relying on it.
- **Fallback (only if this exact config cannot use managed credentials):** create a Secrets
  Manager secret out-of-band (generated password, never in Git/params), set the RDS master
  password from it, and grant the Lambda `GetSecretValue` on that ARN. Still no plaintext in
  source/params.

### 5.2 Private service connectivity / interface endpoints
- **S3 Gateway Endpoint** — private S3 for EC2 upload/artifact + Lambda read (route-based,
  no hourly charge).
- **Secrets Manager Interface Endpoint (PrivateLink)** — **the primary demonstrable
  private-PaaS bonus.**
- **CloudWatch Logs Interface Endpoint** — retained as an additional private-service
  demonstration; removes the last internet dependency for logging.
- Each interface endpoint: one ENI per selected app AZ, **private DNS enabled**, `sg-vpce`
  inbound 443 only from the workloads that use that service.

### 5.3 CloudWatch dashboard + alarms
- **Dashboard widgets:** ALB `RequestCount`, `HTTPCode_ELB_5XX_Count`, `HealthyHostCount`/
  `UnHealthyHostCount`; EC2/ASG `CPUUtilization`; Lambda `Invocations`/`Errors`/`Duration`;
  RDS `CPUUtilization`/`DatabaseConnections`/`FreeStorageSpace`.
- **Alarms (small, demonstrable):**
  | Alarm | Metric | Condition (candidate) |
  |-------|--------|-----------------------|
  | Lambda errors | `AWS/Lambda Errors` | ≥ 1 in 5 min |
  | ALB 5XX | `HTTPCode_ELB_5XX_Count` | ≥ 1 (sum) in 5 min |
  | Unhealthy targets | `UnHealthyHostCount` | ≥ 1 for 5 min |
  | App CPU high | ASG `CPUUtilization` | > 70% for 5 min |
  | RDS CPU high | RDS `CPUUtilization` | > 80% for 5 min |
  | RDS connections | `DatabaseConnections` | > threshold for 5 min |

## 6. Simpler NAT-free alternatives (considered)
- **SSM-pull at runtime instead of a builder:** still needs egress + internet for
  `pip`/`dnf`, so it does not remove the build problem. The custom-AMI approach is retained.
- **CodeDeploy/CodeBuild:** more moving parts and cost; overkill for a short demo.
- **Trade-off:** temporary-builder + custom-AMI is the simplest approach that keeps runtime
  instances fully private with **no NAT** and no runtime internet.

## 7. Constraints to honor during implementation
- Verify the caller identity (non-root) before every state-changing AWS CLI call.
- No quota-increase requests. Live ASG max 4 fits the 8-vCPU quota (4 x t3.micro).
- T2 **standard** credit mode everywhere. No Unlimited.
- No secrets in repo/AMI/user-data/CFN params; fetch at runtime.
- No GitHub token on instances; builder pulls artifacts from private S3.
- Everything tagged (e.g., `Project=nagp-aws`) for clean teardown.
- **RDS cleanup controls (mandatory):** the CloudFormation RDS instance must use
  `DeletionPolicy: Delete`, `UpdateReplacePolicy: Delete`, `DeletionProtection: false`,
  `DeleteAutomatedBackups: true`, and `BackupRetentionPeriod: 0` so no final/automated
  snapshot is retained (default CFN behavior can retain one). See `COST_AND_CLEANUP.md §3`.

## 8. Assignment-requirement traceability matrix
Every mandatory + bonus requirement mapped to component, phase, evidence, and cleanup.
Phases: **F**=Foundation stack, **B**=Builder step, **W**=Workload stack, **O**=Ops/Monitoring, **D**=Demo, **C**=Cleanup.

| # | Requirement (from ASSIGNMENT.md) | Planned AWS component / control | Phase | Evidence / demo location | Cleanup responsibility |
|---|----------------------------------|--------------------------------|-------|--------------------------|------------------------|
| 1 | IAM users & groups | `nagp-app-deployers` group + `nagp-deployer` user (MFA, no keys) | W | Walkthrough IAM; policy JSON screenshot | Delete user/group/policies (CFN or manual) |
| 2 | Least-privilege permissions | Builder/EC2/Lambda roles scoped to prefixes/ARNs (SECURITY_DESIGN §3) | W | Walkthrough; role policy JSON | Delete roles/instance profiles |
| 3 | One VPC | VPC 10.20.0.0/16 | F | Walkthrough VPC | Delete VPC (stack) |
| 4 | ≥2 AZs | us-east-1a, us-east-1b | F | Subnet AZ columns | n/a (logical) |
| 5 | 2 public subnets | 10.20.0.0/24, 10.20.1.0/24 | F | Subnet list | Delete subnets (stack) |
| 6 | 2 private app subnets | 10.20.10.0/24, 10.20.11.0/24 | F | Subnet list | Delete subnets (stack) |
| 7 | 2 private db subnets | 10.20.20.0/24, 10.20.21.0/24 | F | Subnet list + DB subnet group | Delete subnets/subnet group |
| 8 | Internet Gateway | IGW attached to VPC | F | Route tables | Detach + delete IGW |
| 9 | NAT Gateway (conceptual) | Diagram only; **not deployed** | F(doc) | Diagram + walkthrough note | n/a (none created) |
| 10 | EC2-hosted application | t3.micro Flask/Gunicorn in ASG | B/W | App demo; instance list | ASG delete → instances terminate |
| 11 | Public HTTP access | Internet-facing ALB HTTP:80 | W | Browser demo | Delete ALB/listener |
| 12 | Application Load Balancer | ALB + target group :8000 | W | Walkthrough; healthy targets | Delete ALB/TG |
| 13 | Auto Scaling Group | ASG min2/desired2/max4 (`AsgMaxSize` 2 or 4) + target-tracking | W | Walkthrough; ASG activity | Delete ASG |
| 14 | Security Groups | 6 SGs (SECURITY_DESIGN §1) | F | Walkthrough SG rules | Delete SGs (after ENIs drain) |
| 15 | NACLs | 3-tier NACLs incl. Lambda TCP+UDP ephemeral | F | Walkthrough NACLs | Delete NACLs |
| 16 | Private S3 storage | Bucket BPA + SSE, `uploads/` | W | Object screenshot | Empty + delete bucket |
| 17 | S3 ObjectCreated trigger | Notification on `uploads/` only | W | Lambda invocation log | Remove notification / delete bucket |
| 18 | Python Lambda (boto3) | VPC Lambda + PyMySQL | W | Lambda config + log | Delete function/event source |
| 19 | Lambda reads metadata/content type | `HeadObject`/event | W | Log line with content type | n/a |
| 20 | Lambda writes name/type/timestamp to RDS | INSERT into `document_uploads` | W/D | Controlled read output | n/a |
| 21 | RDS not publicly accessible | `PubliclyAccessible=false`, private subnets | W | RDS config screenshot | Delete RDS |
| 22 | Only Lambda connects to RDS | `sg-rds` inbound 3306 = `sg-lambda` only | F/W | SG rule screenshot | Delete SG |
| 23 | Lambda logs to CloudWatch | Logs via interface endpoint | W/O | Log group | Delete log group |
| 24 | Multi-AZ / HA design | HA app tier (ALB+ASG 2 AZs); DB Multi-AZ-ready (Single-AZ actual) | F/W | Walkthrough HA wording | n/a |
| 25 | Architecture diagram | Mermaid + textual | doc | ARCHITECTURE.md | n/a |
| 26 | Component documentation | Design docs set | doc | docs/* | n/a |
| 27 | ≤2-min app demo | Upload→S3→Lambda→RDS | D | Recording | n/a |
| 28 | ≤8-min config walkthrough | Full console tour | D | Recording | n/a |
| 29 | Source ZIP | App + Lambda + CFN | doc | Deliverable ZIP | n/a |
| 30 | Setup/deploy/dependency docs | This file + README | doc | docs/* | n/a |
| 31 | Assumptions/limitations | DECISIONS.md | doc | DECISIONS.md | n/a |
| 32 | Complete cleanup | Dependency-aware teardown | C | COST_AND_CLEANUP.md + checklist | This plan |
| B1 | **Secrets Manager** | RDS-managed master secret; Lambda `GetSecretValue` | W | Secret name + Lambda code | Delete secret |
| B2 | **Private PaaS / interface endpoint** | Secrets Manager (primary) + Logs interface endpoints; S3 gateway | F | Walkthrough endpoints | Delete endpoints |
| B3 | **CloudWatch dashboard** | 1 dashboard (widgets §5.3) | O | Dashboard screenshot | Delete dashboard |
| B4 | **CloudWatch alarms** | Alarm set (§5.3) | O | Alarm states | Delete alarms |

**No mandatory or bonus requirement is left unmapped.**
