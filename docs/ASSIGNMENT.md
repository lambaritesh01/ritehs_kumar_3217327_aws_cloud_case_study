# ASSIGNMENT — NAGP AWS Cloud Computing & Network Security

> This document records the case-study contract as provided. It must not invent
> requirements. Anything not stated by the assignment is marked as an open
> question in `DECISIONS.md`, not assumed here.

## Scenario
An insurance company needs a cloud MVP that lets users **upload insurance
documents**. The solution must be built on AWS with proper networking, security
segmentation, least-privilege identity, and an automated document-processing
flow, following AWS best practices for a multi-tier, highly available design.

## Objective
Design and deploy a secure, highly available AWS environment hosting a Python
web application for insurance document upload, with an event-driven processing
pipeline and a securely isolated database — then demonstrate it and fully clean
it up.

## IAM requirements
- IAM users and groups.
- Least-privilege permissions (grant only what each role/component needs).

## Networking requirements
- One VPC.
- At least 2 Availability Zones.
- 2 public subnets.
- 2 private application subnets.
- 2 private database subnets.
- Internet Gateway.
- NAT Gateway — shown conceptually in the architecture; actual deployment is a
  separate cost-driven decision (see `DECISIONS.md`).
- Security Groups.
- Network ACLs (NACLs).

## Application requirements
- Python application stack.
- Flask web application (document upload).
- Public Application Load Balancer (ALB) in the public subnets.
- EC2 application instances in the private application subnets.
- Auto Scaling Group for the application tier.

## S3 / Lambda flow
- Private S3 bucket for uploaded documents (not public).
- S3 upload event triggers a Python Lambda function.
- Lambda uses **boto3**.
- Lambda performs processing and interacts with the database as designed.

## RDS security
- Amazon RDS database instance.
- RDS must be reachable **only from the Lambda function** (network + security
  group isolation); not publicly accessible, not reachable from the web tier
  directly unless the design explicitly requires it.

## Observability
- CloudWatch Logs for application / Lambda / relevant components.

## Deliverables
- Working AWS insurance document-upload MVP meeting all mandatory requirements.
- Architecture covering VPC, subnets (public / private app / private db across
  2 AZs), IGW, NAT (conceptual), ALB, EC2 + ASG, S3, Lambda, RDS, Security
  Groups, NACLs, and CloudWatch.
- Flask web application (Python).
- Python Lambda (boto3) triggered by S3 upload.
- Demonstration of the end-to-end upload → S3 → Lambda → RDS flow.
- Complete cleanup of all created AWS resources after the demonstration.

## Bonus requirements (ALL in scope)
- **Secrets Manager** implementation (e.g., DB credentials retrieved securely).
- **Private AWS service connectivity / VPC endpoint(s)** so private-subnet
  components reach AWS services without traversing the public internet.
- **CloudWatch dashboard and alarm(s)**.

## Cleanup requirement
Complete teardown of every provisioned AWS resource after the demonstration is a
**formal, graded requirement** — not optional. Plan cleanup alongside creation.

## Non-negotiable constraints (project-level)
- Preferred region `us-east-1`.
- No secrets committed to the repository.
