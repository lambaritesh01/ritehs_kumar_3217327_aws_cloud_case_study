# Component Description

Region **us-east-1**, two AZs (**us-east-1a**, **us-east-1b**). Components are created by
three CloudFormation stacks (`infra/foundation.yaml`, `infra/builder.yaml`,
`infra/application.yaml`).

| Component | Purpose | Placement | Key configuration | Security relationship |
|-----------|---------|-----------|-------------------|-----------------------|
| VPC | Network boundary | Region | `10.20.0.0/16`, DNS support/hostnames on | Contains all tiers |
| Public subnets (x2) | ALB + temporary builder | 1a `10.20.0.0/24`, 1b `10.20.1.0/24` | `MapPublicIpOnLaunch=true` | Internet-facing tier |
| Private app subnets (x2) | EC2 app + Lambda ENIs | 1a `10.20.10.0/24`, 1b `10.20.11.0/24` | No public IP | No inbound internet |
| Private DB subnets (x2) | RDS | 1a `10.20.20.0/24`, 1b `10.20.21.0/24` | No public IP, no internet route | Database tier |
| Internet Gateway | Public ingress/egress | VPC | Public route table `0.0.0.0/0` → IGW | Serves ALB + builder |
| Route tables (x3) | Tier routing | Public / app / db | Private tables have **no** `0.0.0.0/0` route | Enforces no-internet for private tiers |
| NACLs (x3) | Stateless subnet guardrails | Public / app / db | App tier allows TCP **and** UDP ephemeral (Lambda VPC/DNS needs both) | Coarse subnet controls; SGs enforce identity |
| ALB SG | Restrict ALB | VPC | Inbound 80 from `0.0.0.0/0`; egress 8000 → App SG | Public entry point |
| App SG | Restrict app tier | VPC | Inbound 8000 from ALB SG only; **no DB egress** | App cannot reach RDS |
| Lambda SG | Restrict Lambda | VPC | No inbound; egress 3306 → RDS SG, 443 → endpoints | Only path to RDS |
| RDS SG | Restrict database | VPC | **Inbound 3306 from Lambda SG only** | Core isolation invariant |
| Endpoint SGs (x2) | Restrict interface endpoints | VPC | Inbound 443 from Lambda/App as needed | Private AWS API access |
| Builder SG | Restrict builder | VPC | **Zero inbound**; egress 80/443 | No SSH, build-time only |
| Application Load Balancer | Public HTTP entry | Public A+B | Internet-facing, listener HTTP:80 | Forwards to App SG:8000 |
| Target group | App health/routing | VPC | HTTP:8000, health check `/health` | Registers ASG instances |
| Launch template | EC2 definition | — | Custom AMI, t3.micro, standard credits, IMDSv2, encrypted root, no key pair; user-data writes non-secret env then restarts the service | App instance profile |
| Auto Scaling Group | App capacity/HA | Private app A+B | min 2 / desired 2 / max 4; target-tracking CPU 50% | Two-AZ self-healing |
| Custom AMI | Prebuilt app runtime | Region (private) | AL2023 + Python 3.11 venv + Flask/Gunicorn/boto3 + systemd service; encrypted snapshot | Removes runtime internet need |
| S3 bucket | Document + artifact storage | Region | BPA on, `BucketOwnerEnforced`, SSE-S3, TLS-only policy; prefixes `artifacts/app/`, `artifacts/lambda/`, `uploads/` | Private; only `uploads/` triggers Lambda |
| S3 Gateway Endpoint | Private S3 access | Public + app route tables | Gateway type (route-based) | EC2 upload + Lambda read without internet |
| Secrets Manager Interface Endpoint | Private secret retrieval (bonus) | App A+B | Interface, private DNS | Lambda → Secrets Manager privately |
| CloudWatch Logs Interface Endpoint | Private logging (bonus) | App A+B | Interface, private DNS | Lambda/EC2 → Logs privately |
| Lambda function | Metadata processor | Private app A+B (VPC) | python3.14, PyMySQL packaged; env `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_SECRET_ARN`/`UPLOAD_PREFIX` (no password); `read_recent` demo mode | Only component that connects to RDS |
| Secrets Manager secret | DB credentials (bonus) | Region | RDS-managed master password, rotation enabled | Lambda `GetSecretValue` on this ARN only |
| RDS instance | Metadata store | Private DB A/B | MySQL 8.0.46, db.t3.micro, 20 GiB gp2, **Single-AZ**, private, encrypted, no final snapshot | Reachable only from Lambda SG |
| DB subnet group | RDS placement | Private DB A+B | Spans **both** AZs (Multi-AZ-ready) | Enables future Multi-AZ |
| CloudWatch dashboard (bonus) | Operational view | Region | `nagp-overview`: ALB, ASG, Lambda, RDS widgets | Read-only observability |
| CloudWatch alarms (bonus) | Alerting | Region | 6 explicit: Lambda errors, ALB 5XX, unhealthy hosts, ASG in-service<2, RDS CPU, RDS connections | Detects failure conditions |
| IAM group + user | Least-privilege identity | Account | `nagp-developers` group, `nagp-developer` user; read/observe project resources; **no access keys, no console password** | Demonstrates least-privilege IAM |
| Workload IAM roles | Instance/function permissions | Account | Builder (read `artifacts/app/*`), App EC2 (`PutObject uploads/*`), Lambda (uploads read + DB-secret read + logs + ENI) | Scoped least privilege |
| Temporary AMI builder | Build-time only | Public A | t3.micro; installs runtime, builds AMI; **terminated after AMI creation** | Not part of the running system |

## Notes
- The **temporary AMI builder** exists only during the build step and is terminated once
  the custom AMI is available; it is not a runtime component.
- **RDS is Single-AZ** in this deployment (training-account constraint), while the **DB
  subnet group spans both AZs**, so Multi-AZ can be enabled without network changes.
- The **EC2 application never connects to the database**; only the Lambda function does,
  enforced by the RDS security group accepting 3306 solely from the Lambda security group.
