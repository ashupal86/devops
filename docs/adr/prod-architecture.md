ADR-0001: Production Architecture
Status

Accepted

Date

2026-09-30

Context

The Social Links application consists of:

React/Vite frontend

FastAPI backend

SQLAlchemy database layer

SQLite for local development

The application needs a production deployment that can:

Run the frontend and backend as containers.

Run the backend on Amazon EKS.

Scale backend replicas horizontally.

Use Amazon RDS PostgreSQL for persistent production data.

Store container images in Amazon ECR.

Deploy automatically when changes are pushed to the production branch.

Expose the frontend through an external AWS load balancer.

Keep the backend accessible internally through Kubernetes networking.

Allow the backend to communicate privately with RDS.

Decision

The production architecture will use:

Amazon EKS for Kubernetes workloads.

Amazon ECR for container images.

Amazon RDS PostgreSQL for the production database.

Kubernetes Deployment for the backend.

Kubernetes Horizontal Pod Autoscaler for backend scaling.

Kubernetes Service for internal backend networking.

NGINX for serving the React frontend.

AWS Load Balancer for external frontend access.

GitHub Actions for CI/CD.

GitHub OIDC for AWS authentication.

Kubernetes Secrets/AWS Secrets Manager for sensitive configuration.

Architecture
                         Internet
                            |
                            v
                +-----------------------+
                | AWS Load Balancer     |
                | Frontend Service      |
                +-----------+-----------+
                            |
                            v
                +-----------------------+
                | Frontend NGINX Pods   |
                | React static files    |
                +-----------+-----------+
                            |
                   /api requests
                            |
                            v
                +-----------------------+
                | Backend Service       |
                | ClusterIP             |
                +-----------+-----------+
                            |
                            v
                +-----------------------+
                | Backend Deployment    |
                | FastAPI Pods           |
                |                       |
                | HPA scales replicas   |
                +-----------+-----------+
                            |
                            |
                            v
                +-----------------------+
                | Amazon RDS             |
                | PostgreSQL             |
                +-----------------------+

Deployment Flow
Developer
    |
    | git push production branch
    v
GitHub
    |
    v
GitHub Actions
    |
    +---- Run tests
    |
    +---- Build backend image
    |
    +---- Build frontend image
    |
    v
Amazon ECR
    |
    v
Amazon EKS
    |
    +---- Update backend Deployment
    |
    +---- Update frontend Deployment
    |
    v
Production

Consequences
Positive

Backend can scale horizontally.

RDS provides persistent production storage.

Kubernetes provides deployment and restart management.

ECR provides a private AWS container registry.

GitHub Actions automates production deployments.

The backend does not require a public IP.

Frontend and backend can communicate through Kubernetes Services.

The application can be deployed consistently from containers.

Negative

AWS infrastructure introduces additional cost.

EKS is more operationally complex than running a single EC2 instance.

Kubernetes requires additional configuration and monitoring.

RDS requires network, security group, backup, and credential management.

CI/CD becomes more complex than manual deployment.

Alternatives Considered
EC2 + Docker Compose

Rejected for the target architecture because the application requires Kubernetes-based horizontal backend scaling.

SQLite in Production

Rejected because SQLite is not appropriate for the intended horizontally scaled backend architecture.

RDS MySQL

Not selected because the application will use PostgreSQL with SQLAlchemy.

Public Backend Load Balancer

Not selected initially.

The backend will be exposed internally through a Kubernetes Service, while the frontend NGINX proxies /api requests to the backend Service.

Security

The RDS database should not be publicly accessible.

The intended network path is:

Internet
   X
   |
   X
RDS

EKS Backend Pods
       |
       v
Private VPC
       |
       v
RDS


Production database credentials must not be committed to Git.

Rollback

Container images will use immutable Git SHA tags.

Example:

backend:8f3a91c
frontend:8f3a91c


The Kubernetes deployment can therefore be rolled back to a previous image version.

Future Improvements

Potential future improvements include:

AWS Load Balancer Controller

HTTPS/TLS

Route 53

ACM certificates

AWS Secrets Manager integration

CloudWatch monitoring

Prometheus/Grafana

Container vulnerability scanning

Database migration jobs

Blue/green or canary deployments
