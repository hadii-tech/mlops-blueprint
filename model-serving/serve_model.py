import os
import logging
import hvac
import mlflow.pytorch
import torch
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

def get_vault_client():
    vault_addr=os.getenv("VAULT_ADDR","http://vault.vault.svc.cluster.local:8200")
    vault_path_auth=os.getenv("VAULT_PATH_AUTH","auth/kubernetes/login")
    vault_role=os.getenv("VAULT_ROLE","mlops-serving")
    with open("/var/run/secrets/kubernetes.io/serviceaccount/token","r") as f:
        sa_token=f.read()
    client=hvac.Client(url=vault_addr)
    client.auth_kubernetes(role=vault_role, jwt=sa_token, mount_point=vault_path_auth.replace("/login",""))
    if not client.is_authenticated():
        raise Exception("Vault auth failed for serving.")
    return client

# Possibly we might fetch MODEL_URI from vault. For now, we do environment var.
MODEL_URI = os.getenv("MODEL_URI","mlruns/0/some_run/artifacts/pr_autoencoder")

try:
    model = mlflow.pytorch.load_model(MODEL_URI)
    model.eval()
    logging.info(f"Loaded model from {MODEL_URI}")
except Exception as e:
    logging.error(f"Could not load model: {e}")
    model=None

@app.route("/predict", methods=["POST"])
def predict():
    if model is None:
        return jsonify({"error":"No model loaded"}),500
    data=request.get_json(force=True)
    features=data.get("features",[])
    if not isinstance(features,list):
        return jsonify({"error":"features must be a list"}),400

    with torch.no_grad():
        X=torch.tensor([features],dtype=torch.float32)
        reconst=model(X)
        recon_err=torch.mean((reconst - X)**2,dim=1).item()
        return jsonify({"reconstruction_error":recon_err})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"ok"})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=80)
    