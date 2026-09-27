# Scope and Assumptions

## In scope
- Insurance document-upload MVP on AWS.
- Two-AZ, highly available application tier (ALB + EC2 Auto Scaling Group).
- Public HTTP entry via an internet-facing Application Load Balancer.
- Private S3 bucket for uploaded documents.
- Event-driven Python Lambda metadata processor (S3 `ObjectCreated` on `uploads/`).
- Amazon RDS MySQL metadata store, reachable only from the Lambda function.
- Network and security controls: VPC, six subnets, IGW, route tables, NACLs, security
  groups, least-privilege IAM.
- Monitoring: CloudWatch dashboard and alarms.
- Bonus features: Secrets Manager, private VPC service endpoints, CloudWatch dashboard,
  CloudWatch alarms.
- Complete, reproducible teardown.

## Design limitations and assumptions
- **HTTP only.** The assignment requires public HTTP access, so the ALB serves HTTP:80.
  TLS/HTTPS is not configured (would require an ACM certificate and a domain).
- **RDS Single-AZ.** The database runs Single-AZ due to training-account constraints. The
  DB subnet group spans both AZs, so it is Multi-AZ-ready.
- **No NAT Gateway.** Private-subnet AWS access uses the S3 Gateway Endpoint and the
  Secrets Manager / CloudWatch Logs interface endpoints; runtime software is baked into a
  custom AMI, so no outbound internet is needed at runtime.
- **No SSH.** Instances have no key pair and no inbound SSH; the builder uses user-data only.
- **No long-lived AWS access keys.** Workloads use instance/function roles; the assignment
  IAM user has no access keys and no console password.
- **No end-user authentication.** This MVP has no customer identity/authorization layer.
- **Test data only.** The validation upload is a small, harmless text file with no real or
  customer data.
- **Temporary builder.** The AMI builder is created only to bake the AMI and is terminated
  afterward; it is not part of the running system.
- **Ephemeral environment.** The deployment is intended to be recorded and then fully
  removed (see `COST_AND_CLEANUP.md`).

This MVP is not intended to be production-ready for real insurance data.

## Production enhancements
- HTTPS via ACM on the ALB (with HTTP→HTTPS redirect).
- AWS WAF and edge protections.
- Customer authentication and authorization.
- RDS Multi-AZ (and read replicas / automated backups as needed).
- Malware / content scanning of uploaded documents.
- Stronger audit logging and data-retention controls.
- Backup and disaster-recovery policy.
- CI/CD pipeline for build, test, and deployment.
