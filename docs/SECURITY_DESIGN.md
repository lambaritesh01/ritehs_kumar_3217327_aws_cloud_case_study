# SECURITY DESIGN — Security Groups, NACLs, IAM

> **Design frozen; nothing created.** Enforcement model: **Security Groups** provide
> workload identity (stateful, SG-referenced); **NACLs** provide coarse, stateless subnet
> guardrails. Where EC2 and Lambda share the private app subnets, NACLs cannot tell them
> apart — **SGs do** (see NACL note).

## 1. Security Group matrix

### 1.1 ALB SG (`sg-alb`)
| Dir | Proto | Port | Source / Dest | Reason |
|-----|-------|------|---------------|--------|
| In  | TCP | 80 | `0.0.0.0/0` | Public HTTP to the internet-facing ALB |
| Out | TCP | 8000 | `sg-ec2-app` | Forward requests to the Flask app only |

### 1.2 EC2 App SG (`sg-ec2-app`)
| Dir | Proto | Port | Source / Dest | Reason |
|-----|-------|------|---------------|--------|
| In  | TCP | 8000 | `sg-alb` | Only the ALB may reach the app port |
| Out | TCP | 443 | `sg-vpce` | CloudWatch Logs (and SSM if used) via interface endpoints |
| Out | TCP | 443 | S3 prefix list (`pl-…`) | `PutObject` uploads + artifact fetch via S3 Gateway Endpoint |
| — | — | — | **no rule to `sg-rds`** | **EC2 must have NO database connectivity** |

### 1.3 Lambda SG (`sg-lambda`)
| Dir | Proto | Port | Source / Dest | Reason |
|-----|-------|------|---------------|--------|
| In  | — | — | **none** | Lambda is never addressed inbound |
| Out | TCP | 3306 | `sg-rds` | Write metadata to RDS MySQL |
| Out | TCP | 443 | `sg-vpce` | Secrets Manager + CloudWatch Logs via interface endpoints |
| Out | TCP | 443 | S3 prefix list (`pl-…`) | `HeadObject`/`GetObject` via S3 Gateway Endpoint |

### 1.4 RDS SG (`sg-rds`) — **critical invariant**
| Dir | Proto | Port | Source / Dest | Reason |
|-----|-------|------|---------------|--------|
| In  | TCP | 3306 | **`sg-lambda` ONLY** | Only the Lambda function may connect to the DB |
| Out | — | — | none required | DB initiates no outbound |

> No CIDR sources, no EC2 SG, no public access. `PubliclyAccessible=false`.

### 1.5 Interface Endpoint SG (`sg-vpce`)
| Dir | Proto | Port | Source / Dest | Reason |
|-----|-------|------|---------------|--------|
| In  | TCP | 443 | `sg-lambda` | Lambda → Secrets Manager / Logs |
| In  | TCP | 443 | `sg-ec2-app` | EC2 → Logs (app logging) |
| Out | — | — | none required | Endpoint responds statefully |

> Inbound 443 is scoped to exactly the workloads that use each service: Lambda needs
> Secrets Manager + Logs; EC2 needs Logs only. No `0.0.0.0/0` on endpoint SGs.

### 1.6 Builder SG (`sg-builder`, temporary — t3.micro)
| Dir | Proto | Port | Source / Dest | Reason |
|-----|-------|------|---------------|--------|
| In  | — | — | **none** (no SSH) | Bootstrap via user-data; optional SSM Session Manager (no inbound needed) |
| Out | TCP | 443 | `0.0.0.0/0` | Package/pip/artifact downloads to bake the AMI |
| Out | TCP | 80 | `0.0.0.0/0` | Repo mirrors that still use HTTP |

**Inbound SSH is zero:** user-data performs the whole build at boot; if interactive access
is ever needed use SSM Session Manager (outbound 443 only). No key pair / port 22.

## 2. NACL design (stateless, subnet-scoped)
NACLs are stateless, so **return traffic needs explicit ephemeral rules**. Standard client
ephemeral range: **1024–65535**.

### 2.1 Public tier NACL (Public A/B)
| Dir | Rule | Proto | Port | CIDR | Reason |
|-----|------|-------|------|------|--------|
| In  | 100 | TCP | 80 | 0.0.0.0/0 | Client HTTP to ALB |
| In  | 110 | TCP | 1024-65535 | 0.0.0.0/0 | Return traffic (client responses; builder downloads) |
| Out | 100 | TCP | 8000 | 10.20.10.0/24, 10.20.11.0/24 | ALB → EC2 app |
| Out | 110 | TCP | 1024-65535 | 0.0.0.0/0 | Responses to clients |
| Out | 120 | TCP | 443 | 0.0.0.0/0 | Builder package installs (HTTPS) |
| Out | 130 | TCP | 80 | 0.0.0.0/0 | Builder package installs (HTTP) |

### 2.2 Private App tier NACL (Private App A/B) — **Lambda-aware**
| Dir | Rule | Proto | Port | CIDR | Reason |
|-----|------|-------|------|------|--------|
| In  | 100 | TCP | 8000 | 10.20.0.0/24, 10.20.1.0/24 | ALB → EC2 app |
| In  | 110 | TCP | 1024-65535 | 10.20.0.0/16 | TCP return traffic (S3/endpoints/RDS) |
| In  | 120 | **UDP** | 1024-65535 | 10.20.0.0/16 | **Lambda VPC networking** return/UDP (e.g., DNS) |
| Out | 100 | TCP | 443 | 10.20.0.0/16 | To interface endpoints / S3 (in-VPC targets) |
| Out | 110 | TCP | 3306 | 10.20.20.0/24, 10.20.21.0/24 | Lambda ENIs → RDS |
| Out | 120 | TCP | 1024-65535 | 10.20.0.0/16 | TCP responses back to ALB / callers |
| Out | 130 | **UDP** | 1024-65535 | 10.20.0.0/16 | **Lambda VPC networking** UDP (e.g., DNS to VPC resolver) |

> **Why the app-tier ephemeral rules are intentionally broader (TCP *and* UDP):** AWS
> Lambda VPC ENIs (Hyperplane) and the VPC DNS resolver use both TCP and UDP on ephemeral
> ports; DNS in particular is UDP/53 outbound with UDP ephemeral returns. An ordinary
> TCP-only client ephemeral rule would break Lambda name resolution and connectivity to
> the interface endpoints/RDS. EC2 alone would need only TCP ephemeral, but because Lambda
> ENIs share these subnets, the app-tier NACL must permit UDP 1024–65535 as well. This is
> a deliberate, documented widening for correct Lambda operation, not an oversight.

### 2.3 Private DB tier NACL (Private DB A/B)
| Dir | Rule | Proto | Port | CIDR | Reason |
|-----|------|-------|------|------|--------|
| In  | 100 | TCP | 3306 | 10.20.10.0/24, 10.20.11.0/24 | From app subnets (Lambda ENIs) — packet routing |
| In  | 110 | TCP | 1024-65535 | 10.20.10.0/24, 10.20.11.0/24 | Return traffic for DB responses |
| Out | 100 | TCP | 1024-65535 | 10.20.10.0/24, 10.20.11.0/24 | DB responses to Lambda |

**Honest limitation (unchanged):** the DB NACL admits 3306 from the *app subnet CIDRs*,
which contain **both** EC2 and Lambda ENIs. NACLs cannot distinguish them by CIDR. The
guarantee that **only Lambda** reaches RDS is enforced at the **security-group** layer
(`sg-rds` inbound = `sg-lambda` only; EC2 App SG has no DB egress rule). NACLs handle
packet routing/return; SGs are the identity-level enforcement.

## 3. IAM design
### A. Administrative / deploy identity — NOT the assignment least-privilege identity
- A broad administrative identity (`AdministratorAccess`, MFA, no static access keys) used
  only to provision and operate the stacks. Deliberately broad and **separate** from the
  least-privilege assignment identity below.

### B. Assignment developer group + user (least privilege) — planned
- **Group:** `nagp-app-deployers`; **User:** `nagp-deployer` (console + **MFA**, **no
  static access keys**; temporary credentials only).
- **Scope:** only CloudFormation, EC2/VPC networking, ELBv2, Auto Scaling, S3, Lambda,
  RDS, Secrets Manager, CloudWatch, SSM read (AMI parameter), and `iam:PassRole` limited to
  the three workload roles below.
- **Resource-level restriction possible for:** S3 (bucket + prefix ARNs), Secrets Manager
  (secret ARN), RDS (DB ARN), Lambda (function ARN), `iam:PassRole` (exact role ARNs with
  `iam:PassedToService`).
- **Must be `Resource: "*"`:** most `ec2:Describe*`/network *create* actions, ELBv2/ASG/
  CFN `Describe*`, and `ssm:GetParameter*` on the public AMI parameter. Constrain with
  `aws:RequestedRegion = us-east-1` where possible.

### C. Temporary builder role (`role-builder`) — instance profile, ephemeral
| Action | Resource | Reason |
|--------|----------|--------|
| `s3:GetObject` | `arn:aws:s3:::<bucket>/artifacts/app/*` | Fetch the packaged app artifact only |
| (optional) `ssmmessages:*`, `ssm:UpdateInstanceInformation` | `*` | SSM Session Manager (no SSH), if used |
- **No** `uploads/` access, **no** document-upload permission, **no** DB permission, **no**
  Secrets Manager permission. Deleted with the builder.

### D. Production EC2 application role (`role-ec2-app`) — via instance profile
| Action | Resource | Reason |
|--------|----------|--------|
| `s3:PutObject` | `arn:aws:s3:::<bucket>/uploads/*` | Store uploaded documents only |
| (optional) `s3:GetBucketLocation` / `s3:ListBucket` (prefix `uploads/`) | bucket ARN | Only if the app code genuinely needs it |
| `logs:CreateLogStream`, `logs:PutLogEvents` | app log-group ARN | App logging to CloudWatch |
| (optional) `ssmmessages:*`, `ssm:UpdateInstanceInformation` | `*` | SSM Session Manager (no SSH) |
- **No** `GetSecretValue`, **no** RDS/database permission, **no** Lambda admin, **no** broad
  S3 write. EC2 cannot reach the DB.

### E. Lambda execution role (`role-lambda-proc`)
| Action | Resource | Reason |
|--------|----------|--------|
| `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` | Lambda log-group ARN | Lambda logging |
| `s3:GetObject`, `s3:HeadObject` | `arn:aws:s3:::<bucket>/uploads/*` | Read object + metadata |
| `secretsmanager:GetSecretValue` | the DB secret ARN | Fetch DB credentials |
| `ec2:CreateNetworkInterface`, `ec2:DescribeNetworkInterfaces`, `ec2:DeleteNetworkInterface` | `*` (AWS requirement) | VPC Lambda ENI lifecycle |
- **No general S3 write.** ENI actions require `Resource: "*"` (AWS limitation; equals
  `AWSLambdaVPCAccessExecutionRole`). Everything else is ARN-scoped.

### Repo/token boundary
- The private GitHub repo is **never** accessed from EC2/builder via PAT/token. The builder
  obtains the packaged app **from private S3** (`artifacts/app/`) using its instance role.
  No GitHub credential ever lands on an instance.

## 4. Data-protection & transport assumptions
- **S3:** Block Public Access = ON; default encryption (SSE-S3/SSE-KMS) — **encryption at
  rest**; `uploads/` prefix for the event filter; TLS-only bucket policy optional.
- **RDS:** `PubliclyAccessible=false`, **storage encryption at rest** on; credentials only
  via Secrets Manager (prefer RDS-managed master password); **Single-AZ** in this workshop.
- **Secrets Manager:** DB credentials; access limited to the Lambda role ARN; encrypted at
  rest (KMS).
- **In transit:** app↔S3, Lambda↔Secrets Manager, Lambda↔Logs use **HTTPS/TLS** (AWS
  endpoints); Lambda↔RDS is within the VPC (TLS to MySQL optional/recommended).
- **Public app is HTTP:80 only** — the assignment requires public **HTTP** access; TLS/HTTPS
  on the ALB is **not** added (would need a certificate/domain). **Documented workshop
  limitation**; production would front the ALB with ACM/HTTPS + redirect.
- No secrets in the repo, AMI, user-data, CloudFormation parameters, or environment
  documentation; the Lambda fetches DB credentials at runtime.
