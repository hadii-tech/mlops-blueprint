import hvac
import os
import json
import logging
import datetime
import tempfile
import boto3
import glob
import pandas as pd
import numpy as np
import mlflow
import torch
import torch.nn as nn
import torch.optim as optim
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.feature_extraction.text import TfidfVectorizer

logging.basicConfig(level=logging.INFO)

class PullRequestAutoencoder(nn.Module):
    def __init__(self, input_dim=1050, hidden_dim=64):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim//2),
            nn.ReLU()
        )
        self.decoder = nn.Sequential(
            nn.Linear(hidden_dim//2, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, input_dim)
        )
    def forward(self, x):
        return self.decoder(self.encoder(x))

def get_vault_client():
    vault_addr = os.getenv("VAULT_ADDR","http://vault.vault.svc.cluster.local:8200")
    vault_path_auth = os.getenv("VAULT_PATH_AUTH","auth/kubernetes/login")
    vault_role = os.getenv("VAULT_ROLE","mlops-training")
    with open("/var/run/secrets/kubernetes.io/serviceaccount/token","r") as f:
        sa_token = f.read()
    client = hvac.Client(url=vault_addr)
    client.auth_kubernetes(role=vault_role, jwt=sa_token, mount_point=vault_path_auth.replace("/login",""))
    if not client.is_authenticated():
        raise Exception("Vault authentication failed for train_autoencoder.")
    return client

def main():
    vault_secret_path = os.getenv("VAULT_SECRET_PATH","secret/data/mlops/staging/train")
    client = get_vault_client()
    resp = client.secrets.kv.read_secret_path(path=vault_secret_path)
    secrets = resp["data"]["data"]

    mlflow_uri = secrets.get("mlflow_uri","")
    if mlflow_uri:
        mlflow.set_tracking_uri(mlflow_uri)

    do_spaces_endpoint = secrets["do_spaces_endpoint"]
    do_spaces_bucket = secrets["do_spaces_bucket"]

    run_id = os.getenv("PREPROCESS_RUN_ID","")
    if not run_id:
        logging.error("No PREPROCESS_RUN_ID provided, cannot find data run.")
        return

    s3 = boto3.client("s3", endpoint_url=do_spaces_endpoint)
    local_dir = tempfile.mkdtemp()
    prefix = f"preprocess-runs/{run_id}/"

    objs = s3.list_objects_v2(Bucket=do_spaces_bucket, Prefix=prefix)
    if "Contents" not in objs:
        logging.error(f"No parquet found for run_id={run_id} in DO Spaces.")
        return

    for obj in objs["Contents"]:
        key = obj["Key"]
        if key.endswith(".parquet"):
            local_path = os.path.join(local_dir, os.path.basename(key))
            s3.download_file(do_spaces_bucket, key, local_path)
            logging.info(f"Downloaded {key} -> {local_path}")

    part_files = glob.glob(os.path.join(local_dir,"*.parquet"))
    if not part_files:
        logging.error("No parquet files downloaded for training.")
        return
    df = pd.concat([pd.read_parquet(f) for f in part_files], ignore_index=True)
    logging.info(f"Loaded {df.shape[0]} rows for training run_id={run_id}")

    text_cols = ["title","body","labels","author_association"]
    for c in text_cols:
        df[c] = df[c].astype(str)
    df["text_feature"] = df["title"] + " " + df["body"] + " " + df["labels"] + " " + df["author_association"]

    vectorizer = TfidfVectorizer(max_features=1000)
    text_vectors = vectorizer.fit_transform(df["text_feature"]).toarray()
    numeric_cols = ["additions","deletions","changed_files","assignees_count","commits_count"]
    X_num = df[numeric_cols].values
    X = np.hstack((X_num, text_vectors))
    y = df["label"].values

    input_dim = X.shape[1]
    device = "cuda" if torch.cuda.is_available() else "cpu"

    with mlflow.start_run():
        mlflow.log_param("preprocess_run_id", run_id)
        mlflow.log_param("model_type", "Autoencoder")
        mlflow.log_param("input_dim", input_dim)
        autoenc = PullRequestAutoencoder(input_dim, 64).to(device)

        criterion = nn.MSELoss()
        optimizer = optim.Adam(autoenc.parameters(), lr=1e-3)
        X_tensor = torch.tensor(X, dtype=torch.float32).to(device)

        epochs = 10
        for epoch in range(epochs):
            autoenc.train()
            optimizer.zero_grad()
            recon = autoenc(X_tensor)
            loss = criterion(recon, X_tensor)
            loss.backward()
            optimizer.step()
            logging.info(f"Epoch {epoch+1}/{epochs}, Reconst. Loss={loss.item():.4f}")

        autoenc.eval()
        with torch.no_grad():
            out = autoenc(X_tensor)
            recon_err = torch.mean((out - X_tensor)**2, dim=1).cpu().numpy()

        import numpy as np
        mean_err = np.mean(recon_err)
        std_err = np.std(recon_err)
        threshold = mean_err + 2*std_err
        preds = (recon_err>threshold).astype(int)

        f1 = f1_score(y, preds)
        auc = roc_auc_score(y, recon_err)
        mlflow.log_metric("f1_score", f1)
        mlflow.log_metric("roc_auc_score", auc)
        logging.info(f"F1={f1:.3f}, AUC={auc:.3f}")

        mlflow.pytorch.log_model(autoenc, "pr_autoencoder")

if __name__=="__main__":
    main()
    