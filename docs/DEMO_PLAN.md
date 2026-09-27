# Recording Runbook

Two recordings: a functional demo (≤ 2 min) and a configuration walkthrough (≤ 8 min).
Region **us-east-1**. Never show the AWS account number, secret values, the DB password,
credentials, or personal identifiers on screen.

`<alb-dns>` = the application ALB DNS name (application stack output `AlbDnsName`).

---

## A. Functional demo (target 1:40–1:55)

| Time | Action | Say (1–2 sentences) | Do NOT show |
|------|--------|---------------------|-------------|
| 00:00–00:10 | Open `http://<alb-dns>/` in the browser | "This is the insurance document-upload MVP, served publicly through an Application Load Balancer." | account menu |
| 00:10–00:25 | Show the upload page and `http://<alb-dns>/health` (returns `{"status":"ok"}`) | "The app is healthy behind the ALB; EC2 instances run privately across two AZs." | — |
| 00:25–00:45 | Choose the harmless test file and click upload; show the success response with the returned `uploads/...` key | "The upload succeeds and returns the private S3 object key." | — |
| 00:45–01:05 | In the S3 console, open the bucket → `uploads/` → the new object | "The document is stored privately under the uploads prefix; the bucket blocks public access." | full bucket ARN if it shows the account id |
| 01:05–01:25 | In CloudWatch Logs, open the Lambda log group and show the latest processing entry | "An S3 event triggered the Lambda, which read the object metadata." | — |
| 01:25–01:45 | Invoke the Lambda `read_recent` (or show a prepared result) and show the returned row | "The Lambda wrote the file name, content type, and upload time into RDS; here is the row." | secret value page |
| 01:45–01:55 | Close | "That is the end-to-end flow: browser → ALB → EC2 → S3 → Lambda → Secrets Manager → RDS." | — |

Keep under 2:00.

---

## B. Configuration walkthrough (target 7:15–7:40)

| Time | AWS console page (pre-open) | Point at | Say | Do NOT show |
|------|-----------------------------|----------|-----|-------------|
| 00:00–00:35 | `docs/architecture.svg` | Overall diagram; legend | "Two-AZ app tier, private data tier, no NAT, event-driven processing." | — |
| 00:35–01:15 | IAM → Groups/Users; Roles | `nagp-developers`/`nagp-developer` (no keys); builder/EC2/Lambda roles | "Least-privilege identities; the user has no access keys; workload roles are scoped." | policy pages with account id enlarged |
| 01:15–02:15 | VPC → Subnets, Route tables, Internet gateways | 6 subnets across 2 AZs; public route to IGW; private tables with no 0/0; no NAT | "One VPC, six subnets, IGW for the public tier; private tiers have no internet route and no NAT." | — |
| 02:15–03:00 | VPC → Network ACLs; EC2 → Security Groups | NACL tiers; ALB→app:8000; RDS 3306 from Lambda SG only | "Security groups enforce the chain; only the Lambda SG can reach the database." | — |
| 03:00–03:45 | VPC → Endpoints | S3 Gateway; Secrets Manager + Logs interface endpoints | "Private-subnet access to S3, Secrets Manager, and CloudWatch Logs uses VPC endpoints." | — |
| 03:45–04:40 | EC2 → Load balancers, Target groups, Instances; Auto Scaling groups | ALB (HTTP:80); TG (:8000, `/health`, healthy); 2 private t3.micro; ASG min2/desired2/max4 + target-tracking | "Public ALB to a two-AZ Auto Scaling Group of private instances, with CPU target-tracking." | instance public-IP columns (there are none) |
| 04:40–05:20 | S3 → bucket; Lambda → function | Block Public Access, encryption; `uploads/` event notification; Lambda VPC config + trigger | "Private bucket; only the uploads prefix triggers the VPC-attached Python Lambda." | — |
| 05:20–06:10 | Secrets Manager → secret (list only); RDS → database | RDS-managed secret (name only); RDS private, encrypted, Single-AZ; SG | "Credentials are RDS-managed in Secrets Manager; the database is private, encrypted, and reachable only from the Lambda." | "Retrieve secret value" page |
| 06:10–06:50 | CloudWatch → Dashboards → `nagp-overview`; Alarms | Widgets; the 6 explicit alarms | "A dashboard and six alarms cover ALB, ASG, Lambda, and RDS health." | — |
| 06:50–07:30 | Diagram / notes | NAT omission, RDS Single-AZ, HTTP-only, cleanup plan | "Key tradeoffs: no NAT (endpoints instead), Single-AZ database for this training account, HTTP MVP; everything is torn down after recording." | — |

End before 8:00.

---

## Recording preparation checklist

Before recording:
- [ ] Close unrelated/private browser tabs; hide the bookmarks bar and any personal details.
- [ ] Ensure the AWS console account menu (top-right) is closed so the account number is not visible.
- [ ] Use only the harmless test document (`nagp-validation.txt`).
- [ ] Pre-open the required tabs listed above.
- [ ] Set a comfortable browser zoom (100–110%).
- [ ] Confirm both ALB targets are healthy.
- [ ] Confirm RDS is available.
- [ ] Confirm the Lambda is healthy (no recent errors).
- [ ] Confirm the CloudWatch dashboard loads.
- [ ] Confirm the six alarms are in expected states.
- [ ] Confirm `POST /upload` works (a prior successful upload is sufficient).
- [ ] Do not leave the Secrets Manager "Retrieve secret value" page open.

After recording:
- [ ] Play back both files to confirm they are readable.
- [ ] Confirm each is within its time limit.
- [ ] Confirm no account number, secret, or credential was visible.
- [ ] Preserve the recordings before any cleanup.
