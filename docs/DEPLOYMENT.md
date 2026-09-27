# Deployment Guide

Reproducible deployment of the insurance document-upload MVP in **us-east-1**. Commands
are shown generically; substitute the placeholders:

- `<artifact-bucket-name>` — a globally unique S3 bucket name
- `<base-ami-id>` — the Amazon Linux 2023 x86_64 AMI id (resolved from SSM, below)
- `<custom-app-ami-id>` — the custom application AMI produced by the builder
- `<app-key>` — `artifacts/app/app-<shortsha>.zip`
- `<lambda-key>` — `artifacts/lambda/lambda-<shortsha>.zip`
- `<lambda-arn>` — the deployed processor Lambda ARN (from the application stack output)

Run AWS CLI commands with credentials for an account/region you control (us-east-1).

## 1. Prerequisites
- AWS CLI v2, authenticated to your account (non-root), region `us-east-1`.
- Python 3.14 locally to build/test.
- Permissions to create the resources in the templates (VPC, EC2, ELB, ASG, S3, Lambda,
  RDS, IAM, CloudWatch, VPC endpoints).

## 2. Build and test artifacts
```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\scripts\Test-Local.ps1            # unit tests + syntax
.\scripts\Test-Infrastructure.ps1   # cfn-lint + safety checks
.\scripts\Build-Artifacts.ps1       # dist/app/app.zip, dist/lambda/lambda.zip
```

## 3. Foundation stack
```
aws cloudformation create-stack --stack-name nagp-foundation \
  --template-body file://infra/foundation.yaml \
  --parameters ParameterKey=ArtifactBucketName,ParameterValue=<artifact-bucket-name> \
  --capabilities CAPABILITY_NAMED_IAM --region us-east-1
aws cloudformation wait stack-create-complete --stack-name nagp-foundation --region us-east-1
```
Leave `UploadLambdaArn` empty on first deploy.

## 4. Upload artifacts
```
aws s3api put-object --bucket <artifact-bucket-name> --key <app-key>    --body dist/app/app.zip       --content-type application/zip
aws s3api put-object --bucket <artifact-bucket-name> --key <lambda-key> --body dist/lambda/lambda.zip  --content-type application/zip
```

## 5. Temporary builder
Resolve the base AMI, then deploy the builder:
```
aws ssm get-parameters --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --region us-east-1 --query "Parameters[0].Value" --output text   # -> <base-ami-id>

aws cloudformation create-stack --stack-name nagp-builder \
  --template-body file://infra/builder.yaml \
  --parameters ParameterKey=FoundationStackName,ParameterValue=nagp-foundation \
               ParameterKey=BaseAmiId,ParameterValue=<base-ami-id> \
               ParameterKey=AppArtifactKey,ParameterValue=<app-key> \
  --region us-east-1
aws cloudformation wait stack-create-complete --stack-name nagp-builder --region us-east-1
```
The stack completes only after the bootstrap succeeds (WaitCondition).

## 6. Create the custom AMI
```
aws ec2 create-image --instance-id <builder-instance-id> \
  --name "nagp-app-<shortsha>-<timestamp>" \
  --description "NAGP document upload application <shortsha>" --region us-east-1   # -> <custom-app-ami-id>
aws ec2 wait image-available --image-ids <custom-app-ami-id> --region us-east-1
```
(`<builder-instance-id>` is the `BuilderInstanceId` stack output.) Tag the AMI and its
snapshot with `Project`, `Purpose=application-ami`, `SourceCommit`.

## 7. Delete the builder
```
aws cloudformation delete-stack --stack-name nagp-builder --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name nagp-builder --region us-east-1
```

## 8. Application stack
```
aws cloudformation create-stack --stack-name nagp-application \
  --template-body file://infra/application.yaml \
  --parameters ParameterKey=FoundationStackName,ParameterValue=nagp-foundation \
               ParameterKey=AppAmiId,ParameterValue=<custom-app-ami-id> \
               ParameterKey=LambdaArtifactKey,ParameterValue=<lambda-key> \
               ParameterKey=AsgMaxSize,ParameterValue=4 \
  --capabilities CAPABILITY_IAM --region us-east-1
aws cloudformation wait stack-create-complete --stack-name nagp-application --region us-east-1
```
`AsgMaxSize`: use **2** on accounts limited to a 5-vCPU Standard EC2 quota, or **4** when
the quota supports four t3.micro instances (8 vCPU).

## 9. Wire the S3 notification
Read the processor Lambda ARN (`UploadProcessorFunctionArn` output) and update the
foundation stack so `uploads/` events invoke it:
```
aws cloudformation update-stack --stack-name nagp-foundation \
  --template-body file://infra/foundation.yaml \
  --parameters ParameterKey=ArtifactBucketName,ParameterValue=<artifact-bucket-name> \
               ParameterKey=UploadLambdaArn,ParameterValue=<lambda-arn> \
  --capabilities CAPABILITY_NAMED_IAM --region us-east-1
aws cloudformation wait stack-update-complete --stack-name nagp-foundation --region us-east-1
```

## 10. Validate
- `GET http://<alb-dns>/` and `GET http://<alb-dns>/health` return 200.
- Upload a test file via `POST /upload`; confirm the object under `s3://<bucket>/uploads/`.
- Invoke the Lambda with `{"action":"read_recent","limit":5}` and confirm the metadata row.

Teardown is documented in `COST_AND_CLEANUP.md`.
