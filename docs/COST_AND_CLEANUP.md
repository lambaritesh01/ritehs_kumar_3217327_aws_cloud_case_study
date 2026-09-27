# COST & CLEANUP — NAGP AWS MVP

> **Design only.** New personal AWS account (credit-backed **Free plan**). A Zero-Spend
> Budget and Free-Tier alerts already exist. **Do not assume "free"** — the modern Free
> plan is credit-based and differs from the legacy 12-month Free Tier. No account IDs or
> billing emails appear here.

## 1. Cost-sensitive components
| Component | Charge model | Notes / mitigation |
|-----------|--------------|--------------------|
| **ALB** | Per hour + LCU | Always billable while it exists; delete promptly. A few hours ≈ cents. |
| **RDS instance (Single-AZ)** | Per instance-hour + storage | `db.t3.micro`, 20 GiB, **Single-AZ** (actual). Free-plan credits may cover; do not assume. |
| **RDS Multi-AZ** | ~2× instance + storage | **Production-only; NOT deployed here.** Standby would double cost; the Free-plan/Free-Tier constraints do not support it and we intentionally avoid a Paid-plan upgrade. |
| **EC2 (2× t3.micro)** | Per instance-hour + EBS | Two instances (one/AZ), Free-plan eligible, **standard** CPU-credit mode (never Unlimited). Keep runtime short. |
| **Temporary builder (t3.micro)** | Instance-hour + EBS | Minutes only; terminate immediately after `create-image`. |
| **AMI + EBS snapshot** | Snapshot GB-month | Small but lingers after teardown — must deregister AMI + delete snapshot. |
| **Interface endpoints** | ~$/AZ/hour + data | 2 endpoints × 2 AZ; ≈ $0.04/hr total — trivial for hours, but delete. |
| **S3 Gateway endpoint** | **No hourly charge** | Route-based; only S3 storage/requests apply. |
| **Secrets Manager** | Per secret/month + API calls | One secret; prorated; delete with short recovery window. |
| **CloudWatch** | Dashboards (>3), alarms, logs ingest/storage | Keep 1 dashboard + few alarms; delete log groups at cleanup. |
| **S3 storage/requests** | GB-month + requests | Tiny demo files; empty bucket at teardown. |
| **NAT Gateway** | Hourly + data | **Not deployed** — avoided entirely (conceptual only). |
| **Data transfer** | Egress | Minimal for a local demo. |

## 2. Cost-minimization strategy
1. **Smallest eligible sizes:** `t3.micro` app + builder (2 vCPU, Free-plan eligible,
   **standard** credits), `db.t3.micro`, 20 GiB gp2, minimal Lambda memory.
2. **No NAT Gateway** — the single biggest always-on avoidable cost; replaced by VPC
   endpoints + custom AMI.
3. **No quota-increase request** — the live ASG runs 2 × t3.micro (4 vCPU steady state,
   max 4 = 8 vCPU), within the 8-vCPU Standard EC2 quota.
4. **RDS Single-AZ (actual)** — no Multi-AZ standby cost; **no Paid-plan upgrade** solely
   for the assignment. Multi-AZ is documented as production-only.
5. **Very short runtime:** provision → validate → record demo → **tear down same day**.
   Do not leave the ALB/RDS/EC2 running overnight.
6. **Builder is ephemeral:** terminate right after AMI creation.
7. **Immediate artifact cleanup:** deregister AMI + delete its snapshot; empty + delete
   S3 (`artifacts/*` and `uploads/*`); delete secret; delete log groups.
8. **Interface endpoints + ALB remain cost-sensitive:** delete promptly at teardown.
9. **Rely on existing guardrails:** Zero-Spend Budget + Free-Tier alerts remain in place
   as a backstop.

## 3. Required CloudFormation cleanup controls (RDS especially)
Complete resource cleanup is a **graded requirement**, and the **default CloudFormation
behavior for a standalone `AWS::RDS::DBInstance` can retain a final snapshot** on stack
delete. The implementation MUST therefore set, where applicable, on the RDS instance
(and other stateful resources) so nothing is retained:

```yaml
# AWS::RDS::DBInstance (temporary workshop database)
DeletionPolicy: Delete
UpdateReplacePolicy: Delete
Properties:
  DeletionProtection: false
  DeleteAutomatedBackups: true
  BackupRetentionPeriod: 0        # no automated backups for this throwaway DB
```

- `DeletionPolicy: Delete` + `UpdateReplacePolicy: Delete` — stop CFN from keeping/
  snapshotting the DB on delete/replace.
- `DeletionProtection: false` — allow deletion.
- `DeleteAutomatedBackups: true` and `BackupRetentionPeriod: 0` — no lingering automated
  backups. Revisit only if later technical validation shows a concrete reason (e.g., the
  chosen config rejects `0`), and record that reason here.

> These are documentation-only requirements at this step — no template is created yet.

## 4. Dependency-aware cleanup order
Prefer **CloudFormation stack deletion** (reverses creation automatically); the items
below are the correct order and the manual pre-steps CFN cannot do by itself.

1. **Pre-step — S3 event notification:** update the foundation stack with
   `UploadLambdaArn=""` to remove the bucket→Lambda `uploads/` notification before
   deleting the Lambda/application stack (avoids invocations during teardown).
2. **Pre-step — empty S3 bucket:** delete all objects (and versions/markers if
   versioned); CloudFormation cannot delete a non-empty bucket.
3. **Auto Scaling Group** — set desired/min = 0, then delete the ASG (terminates EC2).
4. **ALB listener → ALB → Target Group.**
5. **Lambda function** (and its event source mapping/permission).
6. **RDS instance** (skip final snapshot for the demo, or take one and delete later) →
   then **DB subnet group**.
7. **VPC interface endpoints** (Secrets Manager, Logs) → **S3 gateway endpoint**.
8. **S3 bucket** (now empty).
9. **Secrets Manager secret** (force delete / short recovery window).
10. **CloudWatch** dashboard, alarms, and log groups (app + Lambda + RDS).
11. **IAM** assignment resources (roles, instance profile, `nagp-deployer`,
    `nagp-app-deployers`, custom policies) — if created outside CFN.
12. **Custom AMI:** deregister AMI → delete backing **EBS snapshot**.
13. **Networking:** SGs (after ENIs drain — Lambda ENIs can linger a few minutes),
    NACLs, route tables, subnets, detach + delete **IGW**, delete **VPC**.
14. **Delete the CloudFormation stacks** themselves (workload, then foundation) — with
    CFN most of 3–13 happen automatically in reverse dependency order.
15. **Temporary artifacts:** local temp scripts, any exported parameters.

> Watch-outs: non-empty S3 blocks bucket delete; RDS with deletion protection blocks
> delete; Lambda ENIs delay SG/subnet delete; AMI snapshots survive stack deletion.

## 5. Final cost / billing verification checklist
Run read-only with the AWS CLI after teardown; confirm **zero** of:
- [ ] EC2 / ASG instances (running/stopped) — `ec2 describe-instances`, `autoscaling describe-auto-scaling-groups`
- [ ] EBS volumes — `ec2 describe-volumes`
- [ ] **Custom AMI** (self) — `ec2 describe-images --owners self`
- [ ] **EBS snapshot created by the AMI** (self) — `ec2 describe-snapshots --owner-ids self`
- [ ] Load balancers + target groups (**ALB**) — `elbv2 describe-load-balancers`, `describe-target-groups`
- [ ] RDS instances + DB subnet groups — `rds describe-db-instances`, `rds describe-db-subnet-groups`
- [ ] **RDS manual snapshots** — `rds describe-db-snapshots --snapshot-type manual`
- [ ] **RDS automated backups** (incl. retained) — `rds describe-db-instance-automated-backups`
- [ ] Elastic IPs / NAT gateways — `ec2 describe-addresses`, `describe-nat-gateways` (expect none)
- [ ] **Interface + gateway VPC endpoints** — `ec2 describe-vpc-endpoints`
- [ ] **Non-empty / leftover S3 bucket** (objects + versions) — `s3api list-buckets`, `s3api list-object-versions`
- [ ] **Secrets Manager secret** (incl. scheduled-for-deletion) — `secretsmanager list-secrets`
- [ ] Lambda functions — `lambda list-functions`
- [ ] CloudWatch log groups / alarms / dashboards
- [ ] Custom VPC deleted (only the default remains) — `ec2 describe-vpcs`
- [ ] IAM assignment user/group/roles/policies removed
- [ ] **Billing:** Cost Explorer / bills show no ongoing charges; **Zero-Spend Budget
      intact and not breached**.

## 6. Final cleanup result (completed 2026-09-26)
Teardown was executed in dependency order and verified against the authoritative AWS
service APIs. All project resources were removed:

- **Application stack** deleted (`nagp-application`).
- **RDS** deleted with **no retained final snapshot**; manual and automated project DB
  snapshot checks both return zero; the RDS-managed Secrets Manager secret was removed
  automatically with the database (none remain, including planned-deletion).
- **S3** bucket emptied (artifacts + upload objects; no versions) and then deleted with the
  foundation stack; `head-bucket` returns 404.
- **Custom AMI** deregistered and its **EBS snapshot deleted** (both confirmed absent).
- **Foundation stack** deleted: VPC, six subnets, IGW, route tables, NACLs, security
  groups, the S3 gateway and both interface **VPC endpoints**, the DB subnet group, the
  assignment IAM user/group, and the workload IAM roles/instance profiles are all gone.
- **ALB / target group / launch template / Auto Scaling Group / EC2 instances** removed.
- **Lambda** function and its CloudWatch log group removed.
- **CloudWatch** dashboard and the six explicit alarms removed.
- **Cost-sensitive residuals:** zero — no EC2 instances, EBS volumes, EBS snapshots, AMIs,
  ALB, RDS, VPC interface endpoints, Secrets Manager project secret, NAT gateways, or
  Elastic IPs remain.

Residual-resource scan: **PASS**. A Resource Groups Tagging API cross-check briefly listed
four already-deleted resources (one snapshot, three VPC endpoints); each was confirmed
deleted via the authoritative EC2 APIs (`NotFound`). The tagging API is eventually
consistent and may list recently-deleted resources for a short period.

Billing and Cost Explorer data can be delayed; cleanup was verified by confirming the
absence of live project resources across the relevant AWS services, not by billing figures.
