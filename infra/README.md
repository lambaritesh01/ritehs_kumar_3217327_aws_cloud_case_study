# Infrastructure (CloudFormation)

Three templates provision the environment. All values are pinned to the frozen design
(`docs/ARCHITECTURE.md`). No NAT gateway is used; private-subnet access to AWS services
is via VPC endpoints, and the application software is baked into a custom AMI.

| Template | Purpose |
|----------|---------|
| `foundation.yaml` | VPC, 6 subnets (2 AZs), IGW, route tables, NACLs, security groups, private S3 bucket, VPC endpoints (S3 gateway + Secrets Manager/Logs interface), DB subnet group, workload instance profiles, and the assignment IAM group/user. Exports IDs for the other stacks. |
| `builder.yaml` | One temporary EC2 builder that installs the app runtime from S3 and configures the Gunicorn service. A `WaitCondition` gates completion. No AMI is created by CloudFormation. |
| `application.yaml` | Single-AZ RDS MySQL (RDS-managed credentials), the VPC Lambda processor, ALB + target group + listener, launch template + Auto Scaling Group with target-tracking, and CloudWatch dashboard + alarms. |

## Local validation
```powershell
.\scripts\Test-Infrastructure.ps1   # cfn-lint + safety checks; no AWS calls
```

## Capabilities
- `foundation.yaml` requires `CAPABILITY_NAMED_IAM` (named IAM group/user).
- `application.yaml` requires `CAPABILITY_IAM` (Lambda execution role).
- `builder.yaml` requires no IAM capability.

## Deployment order
The base AMI id resolves from the public SSM parameter
`/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`.

1. Deploy `foundation.yaml` with `UploadLambdaArn=""` (empty) and a globally unique
   `ArtifactBucketName` (`CAPABILITY_NAMED_IAM`).
2. Upload `dist/app/app.zip` to `artifacts/app/` and `dist/lambda/lambda.zip` to
   `artifacts/lambda/` in the project bucket.
3. Deploy `builder.yaml` (`FoundationStackName`, `BaseAmiId`, `AppArtifactKey`); it
   completes only after a successful bootstrap.
4. Create a custom AMI from the builder instance (`ec2 create-image`), wait until it is
   `available`.
5. Delete the builder stack.
6. Deploy `application.yaml` with the custom `AppAmiId` and `LambdaArtifactKey`
   (`CAPABILITY_IAM`).
7. Read the application stack output `UploadProcessorFunctionArn`.
8. Update `foundation.yaml` setting `UploadLambdaArn=<that ARN>`. This adds the direct
   S3 `uploads/` `ObjectCreated` notification to the Lambda.
9. End-to-end validation.

The Lambda invoke permission is created in the application stack scoped to the project
bucket ARN and account, so wiring the notification in step 8 does not create a circular
dependency (the bucket ARN is derived from the bucket name, known at foundation time).

## Teardown order
1. Update `foundation.yaml` back to `UploadLambdaArn=""` to remove the S3 notification.
2. Empty the S3 bucket (`artifacts/*` and `uploads/*`, including any versions).
3. Delete the application stack (RDS uses `DeletionPolicy: Delete` and takes no final
   snapshot; automated backups are disabled).
4. Deregister the custom AMI and delete its EBS snapshot.
5. The builder stack should already be deleted (step 5 above).
6. Delete the foundation stack.
7. Confirm no leftover RDS snapshots/automated backups, interface endpoints, ENIs, or
   IAM resources remain (see `docs/COST_AND_CLEANUP.md`).

## Parameters (generic examples)
```
ArtifactBucketName = <globally-unique-name>
FoundationStackName = nagp-foundation
BaseAmiId           = <resolved AL2023 x86_64 AMI id>
AppArtifactKey      = artifacts/app/app.zip
AppAmiId            = <custom AMI id>
LambdaArtifactKey   = artifacts/lambda/lambda.zip
```
