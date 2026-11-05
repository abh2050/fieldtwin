# AWS cost and security plan

**Nothing is deployed.** Everything here is a pre-deployment plan. No AWS API was called to write it, and these figures are not measurements. Gate 9 must re-check prices and account permissions, produce an infrastructure diff, and get explicit approval before creating anything.

## Cost approach

Target: at most $150 per month for experimental infrastructure.

| Component | Type | Expected behavior at demo traffic | Control |
|---|---|---|---|
| S3 (site, raw, Parquet) | Recurring, by size | Small: a few GB | Publish validated subsets only, with lifecycle rules |
| CloudFront | Usage | Low | Private distribution, used intermittently |
| API Gateway HTTP API, Lambda | Usage | Near zero when idle | Throttling |
| DynamoDB | Usage | Low with on-demand capacity | Bounded read models, no default scans |
| Cognito | Usage | A handful of users | Admin-created users only |
| CloudWatch Logs | Usage | Low | Short retention |
| SQS | Usage | Low, only if asynchronous replay is built | Bounded batches |
| KMS, Secrets Manager | Recurring, per key or secret | Small | Prefer S3-managed keys, and create secrets only if needed |
| Bedrock | Usage | Zero: disabled by default | Enable only by explicit choice, and log cost per call |
| Fargate batch | Usage | Zero unless run | No service, short-lived tasks only |

**Avoid without explicit approval:** NAT Gateways, always-on load balancers, permanent Fargate services, managed relational databases, Neptune, OpenSearch, and SageMaker endpoints.

**Required before deploying (Gate 9):**

1. Inspect the existing account and permissions.
2. Generate a CDK diff.
3. Write a dollar estimate from current prices with stated usage assumptions, separating recurring from usage-based costs.
4. Configure budget alerts where authorized.
5. Get explicit approval.
6. Verify `make aws-destroy` removes only this project's resources, and keep manifests and reproducibility documents.

## Open risk: `us-east-1` restriction

The organization restricts `us-east-1` and `us-west-2`. Some CloudFront-related features live in `us-east-1`, including certificates for custom domains. The plan is therefore to use the default `cloudfront.net` domain, and Gate 9 must confirm CloudFront itself is allowed by the organization's policies.

## Security controls

| Area | Control | Verified at |
|---|---|---|
| Access | Cognito sign-in with Viewer, Operator, Maintenance Supervisor, and Admin roles | Gate 9 |
| Authorization | Enforced in the backend, not only in the frontend | Gates 7, 9 |
| Storage | Private S3 with CloudFront Origin Access Control and no public buckets | Gate 9 |
| Encryption | TLS in transit, managed encryption at rest | Gate 9 |
| IAM | Least-privilege roles per function | Gate 9 |
| API | Restricted CORS, input validation, throttling, correlation IDs | Gates 7, 9 |
| Audit | Append-only audit events for state changes | Gate 7 |
| Secrets | No credentials in code. `.env` is ignored. Account ID comes from STS at runtime. | Now |
| Logging | Structured JSON, and never log credentials or tokens | Now |
| Physical safety | No integration with real equipment. All recommendations are advisory. | By design |
| Supply chain | Dependency and infrastructure scanning in CI | Gate 9 |

## Trust boundary already relevant

OCD data arrives over unencrypted FTP with no publisher checksum. It should be treated as untrusted input: it is parsed with `expat`, never executed, and rows are validated before use. External entity expansion is not enabled in the parser.
