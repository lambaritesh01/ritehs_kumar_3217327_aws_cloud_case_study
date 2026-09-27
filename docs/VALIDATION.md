# Validation Evidence

Validation date: **2026-09-26**, region **us-east-1**. Results from read-only checks of
the live deployment and the end-to-end functional test. Account identifiers, ARNs, DB
endpoints, and secret values are intentionally omitted.

| Control | Result | Evidence summary |
|---------|--------|------------------|
| One VPC across 2 AZs | PASS | VPC `10.20.0.0/16`; subnets in us-east-1a and us-east-1b |
| Six subnets | PASS | 2 public, 2 private-app, 2 private-db (`…0/24`,`1`,`10`,`11`,`20`,`21`) |
| Internet Gateway | PASS | Attached; public route table `0.0.0.0/0` → IGW |
| No NAT Gateway | PASS | `describe-nat-gateways` returns none |
| No private default route | PASS | Private app/db route tables have no `0.0.0.0/0` |
| NACL tiers | PASS | Separate public/app/db NACLs; app tier allows TCP+UDP ephemeral (Lambda) |
| ALB public | PASS | Internet-facing, 2 public subnets, listener HTTP:80 |
| Target group | PASS | HTTP:8000, health `/health` |
| ALB targets healthy | PASS | 2 targets `healthy` |
| EC2 private | PASS | Instances have no public IP |
| EC2 type/credits | PASS | 2 × t3.micro, standard CPU credits, custom AMI, IMDSv2 required, no key pair |
| EC2 AZ spread | PASS | One instance in us-east-1a, one in us-east-1b |
| ASG configuration | PASS | min 2 / desired 2 / max 4; 2 InService; target-tracking CPU 50% |
| S3 private | PASS | Block Public Access on; `BucketOwnerEnforced`; SSE-S3; TLS-only bucket policy |
| Upload trigger scope | PASS | Notification on `uploads/` only (`s3:ObjectCreated:*`); `artifacts/*` does not trigger Lambda |
| Lambda runtime/VPC | PASS | python3.14, VPC-attached to both private app subnets, Lambda SG |
| Lambda no DB password env | PASS | Env has `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_SECRET_ARN`/`UPLOAD_PREFIX` only |
| Secrets Manager | PASS | RDS-managed secret, status active, rotation enabled |
| RDS private/encrypted/Single-AZ | PASS | MySQL 8.0.46, db.t3.micro, 20 GiB gp2, `PubliclyAccessible=false`, encrypted, MultiAZ=false |
| RDS reachable only from Lambda | PASS | RDS SG inbound 3306 from Lambda SG only (no CIDR, no App SG) |
| DB subnet group | PASS | Spans both private DB subnets (Multi-AZ-ready) |
| VPC endpoints | PASS | S3 Gateway; Secrets Manager Interface; CloudWatch Logs Interface |
| CloudWatch dashboard | PASS | `nagp-overview` exists |
| CloudWatch alarms | PASS | 6 explicit alarms present, all `OK` |
| GET / | PASS | HTTP 200 |
| GET /health | PASS | HTTP 200, `{"status":"ok"}` |
| Controlled upload | PASS | `POST /upload` → HTTP 201; key `uploads/<uuid>/nagp-validation.txt` |
| S3 object | PASS | Private, SSE `AES256`, ContentType `text/plain`, only object under `uploads/` |
| Lambda event processing | PASS | Errors=0; Lambda-errors alarm `OK` |
| RDS metadata row | PASS | `read_recent` returns the row: `file_name=nagp-validation.txt`, `content_type=text/plain`, UTC `upload_timestamp`, matching `s3_key` |
| End-to-end chain | PASS | HTTP → ALB → EC2 → S3 `uploads/` → Lambda → Secrets Manager → RDS |
| No SSH | PASS | No key pair on any instance; builder SG zero inbound; builder terminated |
| No static AWS access key | PASS | Assignment IAM user has no access keys and no login profile |

Stack status at validation: `nagp-foundation` = UPDATE_COMPLETE, `nagp-application` =
UPDATE_COMPLETE.

## Final cleanup verification (2026-09-26) = PASS
After the demonstration, all project resources were torn down and verified absent via the
authoritative AWS service APIs:

- CloudFormation: no `nagp-foundation`, `nagp-application`, or `nagp-builder` stacks.
- Compute/LB: 0 project EC2 instances, ASGs, launch templates, ALBs, or target groups.
- Data: RDS deleted with no retained/manual/automated snapshots; RDS-managed secret removed.
- Storage: S3 bucket emptied and deleted (`head-bucket` 404); custom AMI deregistered and
  its EBS snapshot deleted.
- Network: VPC, subnets, IGW, route tables, NACLs, security groups, and all three VPC
  endpoints removed.
- IAM: assignment user/group and workload roles/instance profiles removed.
- Observability: dashboard and the six alarms removed.
- Cost-sensitive residuals: **0** (no EC2/EBS/snapshots/AMI/ALB/RDS/endpoints/secret/NAT/EIP).

A Resource Groups Tagging API cross-check briefly listed four already-deleted resources;
each was confirmed deleted via the authoritative EC2 APIs (the tagging API is eventually
consistent). Billing data can lag; cleanup was verified by live-resource absence.
