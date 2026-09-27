# Requirements Traceability

Maps each assignment requirement to its implementation, validation evidence, and the
recording section that demonstrates it. Recording sections refer to `DEMO_PLAN.md`
(F = functional demo, W = configuration walkthrough).

## Mandatory requirements
| # | Requirement | Implementation | Evidence | Recording |
|---|-------------|----------------|----------|-----------|
| 1 | IAM users and groups | `nagp-developers` group + `nagp-developer` user (`infra/foundation.yaml`) | VALIDATION: no static keys | W 00:35–01:15 |
| 2 | Least-privilege permissions | Scoped group policy + builder/EC2/Lambda roles (`SECURITY_DESIGN.md §3`) | Role policies scoped to prefixes/ARNs | W 00:35–01:15 |
| 3 | One VPC | VPC `10.20.0.0/16` | VALIDATION: one VPC | W 01:15–02:15 |
| 4 | At least 2 AZs | us-east-1a, us-east-1b | Subnets across both AZs | W 01:15–02:15 |
| 5 | 2 public subnets | `10.20.0.0/24`, `10.20.1.0/24` | VALIDATION: subnets | W 01:15–02:15 |
| 6 | 2 private app subnets | `10.20.10.0/24`, `10.20.11.0/24` | VALIDATION: subnets | W 01:15–02:15 |
| 7 | 2 private DB subnets | `10.20.20.0/24`, `10.20.21.0/24` | DB subnet group spans both | W 01:15–02:15 |
| 8 | Internet Gateway | IGW + public default route | VALIDATION: IGW | W 01:15–02:15 |
| 9 | NAT Gateway (conceptual) | Documented as not deployed; endpoints replace it | Diagram (dashed) | W 01:15–02:15 |
| 10 | Security Groups | 6 SGs (`SECURITY_DESIGN.md §1`) | SG chain validated | W 02:15–03:00 |
| 11 | Network ACLs | 3-tier NACLs incl. Lambda TCP+UDP ephemeral | VALIDATION: NACL tiers | W 02:15–03:00 |
| 12 | EC2-hosted application | Flask/Gunicorn on t3.micro (ASG) | 2 InService, healthy | W 03:45–04:40 |
| 13 | Public HTTP access | Internet-facing ALB HTTP:80 | GET / = 200 | F 00:00–00:25 |
| 14 | Application Load Balancer | ALB + target group `:8000` | 2 healthy targets | W 03:45–04:40 |
| 15 | Auto Scaling Group | ASG min2/desired2/max4 + target-tracking | VALIDATION: ASG | W 03:45–04:40 |
| 16 | Private S3 storage | Bucket BPA + SSE + `uploads/` | S3 object private | W 04:40–05:20 |
| 17 | S3 upload triggers Lambda | `uploads/` `ObjectCreated` notification | Lambda invoked on upload | F 00:45–01:25 |
| 18 | Python Lambda (boto3) | VPC Lambda, python3.14, boto3 + PyMySQL | Lambda config | W 04:40–05:20 |
| 19 | Lambda processes metadata | HeadObject → content type; event time | Row content_type/timestamp | F 01:05–01:45 |
| 20 | Lambda writes name/type/timestamp to RDS | INSERT into `document_metadata` | `read_recent` row | F 01:25–01:45 |
| 21 | RDS not publicly accessible | `PubliclyAccessible=false`, private subnets | VALIDATION: RDS | W 05:20–06:10 |
| 22 | Only Lambda reaches RDS | RDS SG inbound 3306 = Lambda SG only | SG validated | W 05:20–06:10 |
| 23 | CloudWatch Logs | Lambda log group via Logs interface endpoint | Log evidence | F 01:05–01:25 |
| 24 | Multi-AZ / HA design | HA app tier (ALB+ASG 2 AZs); DB Multi-AZ-ready (Single-AZ actual) | Honest HA wording | W 05:20–06:10 |
| 25 | Architecture diagram | `architecture.svg` / `architecture.mmd` | Diagram file | W 00:00–00:35 |
| 26 | Component documentation | `COMPONENTS.md` | Doc | — |
| 27 | End-to-end demonstration | Upload → S3 → Lambda → RDS proven | VALIDATION: end-to-end | F (all) |
| 28 | Complete cleanup | Dependency-aware teardown executed; all resources removed and verified absent | `COST_AND_CLEANUP.md` §6, `VALIDATION.md` (cleanup PASS) | W 06:50–07:30 |

## Bonus requirements
| # | Requirement | Implementation | Evidence | Recording |
|---|-------------|----------------|----------|-----------|
| B1 | Secrets Manager | RDS-managed master secret; Lambda `GetSecretValue` on that secret only | Secret active, no password env | W 05:20–06:10 |
| B2 | Private service connectivity / VPC endpoints | S3 Gateway + Secrets Manager Interface + CloudWatch Logs Interface | 3 endpoints present | W 03:00–03:45 |
| B3 | CloudWatch dashboard | `nagp-overview` (ALB/ASG/Lambda/RDS widgets) | Dashboard exists | W 06:10–06:50 |
| B4 | CloudWatch alarms | 6 explicit alarms | All `OK` | W 06:10–06:50 |

Every mandatory and bonus requirement maps to an implemented component, live evidence, and
a recording moment.
