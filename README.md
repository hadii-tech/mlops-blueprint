# Modern MLOps Blueprint

This project demonstrates a **multi-stage** ML system designed to detect anamolous GitHub Pull Requests. It incorporates **modern cloud-native** technologies tested on Digital Ocean:

- **Vault** for secure secret management.
- **GitHub Actions** for CI/CD (building, ephemeral testing).
- **Argo CD** (GitOps) for continuous deployment to **DigitalOcean** Kubernetes clusters.
- **Argo Rollouts** for blue/green deployment on the model-serving stage.
- **Spark** for distributed preprocessing.
- **MLflow** for experiment tracking and model versioning.
- **Locust** for performance testing.
- **MongoDB** and **DigitalOcean Spaces** for data storage.


Checkout this [blog post](https://mfadhel.com/mlops-blueprint/) outlining the motivation for this repository. 

You will need existing k8s clusters to to execute the machine learning pipelines in this repo (preferably one per environment) which are deployed via ArgoCD. If you need help with this requirement, check out our [existing templates](https://github.com/hadii-tech/cloud-infra) to quickly setup and deploy your own production-ready k8s clusters pre-configred with monitoring, logging, and alerting capabilities in Digital Ocean.

---

##  Stages of the Pipeline

1. **Data-Fetch** (Job)  
   - Runs `fetch_github_data.py`.  
   - Pulls secrets from Vault (GitHub token, Mongo URI).  
   - Upserts PR data into MongoDB.

2. **Spark Preprocess** (Job)  
   - Runs `spark_preprocess.py`.  
   - Uses **Spark** to read from Mongo, create features, stores as parquet files in **DigitalOcean Spaces**.  
   - Secrets for DO Spaces, etc., come from Vault.

3. **ML Training** (Job)  
   - Runs `train_autoencoder.py`. A simple feedforward autoencoder with:
      - Encoder: Compresses input data into a lower-dimensional representation.
      - Decoder: Attempts to reconstruct the input from the compressed representation.
      - A threshold-based anomaly detection method is used:
           - Anomalies are detected when reconstruction errors exceed `mean + 2 * std_dev`.
   - Uses **MLflow** for experiment tracking; references preprocessed data from DO Spaces.  
   - Also references secrets from Vault (like `mlflow_uri`).

4. **Model-Serving** (**Blue/Green** with Argo Rollouts)  
   - A Flask-based ML model serving API that is designed to detect anomalies in pull requests, it is a **long-running** service.  
   - We define a **Rollout** with `blueGreen` strategy in `model-serving-rollout.yaml`.  
   - We can do a “preview” environment, then “promote” to active service for minimal downtime.  
   - We run **Locust** performance tests in ephemeral containers to confirm throughput, latency, etc.

---

## Multi-Branch Approach (Staging & Production)

We use **two** main branches:

1. **staging**  
2. **main** (production)

Each environment references the **same** `argo-apps/base` folder but **different** branches. Thus:
- The **staging** cluster’s Argo CD points to the **staging** branch.  
- The **production** cluster’s Argo CD points to the **main** branch.  

A typical workflow:
1. **Developer** merges changes into **staging** → triggers ephemeral container tests + staging cluster update.
2. Once validated in staging, we **merge staging → main** → triggers ephemeral tests + production cluster update.

No separate “overlays/staging” or “overlays/production” in a single branch are needed. Instead, each environment is captured by its dedicated branch.

---

## CI/CD with GitHub Actions

We define **four** primary workflow files (one per pipeline stage):

1. **data-fetch.yml**
2. **spark-preprocess.yml**
3. **ml-training.yml**
4. **model-serving.yml**

Each workflow:

- **Lint** (flake8) + **Unit Tests** (pytest).
- **Build** the Docker image if that stage’s code changed.
- **Spin up** an **ephemeral container** for integration tests (e.g., checking logs, or hitting an endpoint).
- If tests **pass**, we **push** the Docker image to **DigitalOcean Container Registry**.
- We then **update** the environment (staging or main) references in `argo-apps/base/*.yaml` so Argo CD sees it.

### Single-Build / Reuse of Images

We **build once**, ephemeral-test that image in the pipeline, then reuse the **identical** image for both staging and production. That ensures environment parity: production runs the same artifact tested in staging—no separate rebuild.

---

## 4. Vault for Secrets

Each Python code references environment variables like:

- `VAULT_ADDR`
- `VAULT_PATH_AUTH`
- `VAULT_ROLE`
- `VAULT_SECRET_PATH`

… then uses **hvac** to authenticate with the **Kubernetes auth** method. Actual secrets (e.g., `mongo_uri`, `github_token`, `mlflow_uri`, etc.) reside in Vault under those paths, ensuring we never store secrets in environment variables or Git.

---
## Blue-Green for Model-Serving

Instead of a standard Deployment, we use:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: model-serving
  labels:
    app: model-serving
spec:
  strategy:
    blueGreen:
      activeService: model-serving-active
      previewService: model-serving-preview
      autoPromotionEnabled: false
      # autoPromotionSeconds: 30 # if you want auto promote
```
This approach ensures no downtime when updating the serving container. We keep the old version active while spinning up the new version in “preview” mode. After validation, we promote the new version.

