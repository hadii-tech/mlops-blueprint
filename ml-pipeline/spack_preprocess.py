import logging
import hvac
import os
import datetime
import tempfile
from pymongo import MongoClient
from pyspark.sql import SparkSession
from pyspark.sql.functions import when, col
import boto3
import glob

logging.basicConfig(level=logging.INFO)

def get_vault_client():
    vault_addr = os.getenv("VAULT_ADDR","http://vault.vault.svc.cluster.local:8200")
    vault_path_auth = os.getenv("VAULT_PATH_AUTH","auth/kubernetes/login")
    vault_role = os.getenv("VAULT_ROLE","mlops-spark")
    with open("/var/run/secrets/kubernetes.io/serviceaccount/token") as f:
        sa_token = f.read()
    client = hvac.Client(url=vault_addr)
    client.auth_kubernetes(role=vault_role, jwt=sa_token, mount_point=vault_path_auth.replace("/login",""))
    if not client.is_authenticated():
        raise Exception("Vault auth failed for spark_preprocess.")
    return client

def main():
    vault_secret_path = os.getenv("VAULT_SECRET_PATH","secret/data/mlops/base/spark-preprocess")
    vault_client = get_vault_client()
    resp = vault_client.secrets.kv.v2.read_secret_version(path=vault_secret_path.replace("secret/data/",""))
    secrets = resp["data"]["data"]

    mongo_uri = secrets["mongo_uri"]
    do_spaces_endpoint = secrets["do_spaces_endpoint"]
    do_spaces_bucket = secrets["do_spaces_bucket"]
    run_id = os.getenv("PREPROCESS_RUN_ID", datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S"))

    spark = SparkSession.builder.appName("PR_Anomaly_Spark").getOrCreate()
    c = MongoClient(mongo_uri)
    db = c["mlops_db"]
    coll = db["pull_requests"]
    docs = list(coll.find())
    if not docs:
        logging.warning("No PR docs found. Exiting.")
        spark.stop()
        return

    df = spark.createDataFrame(docs)
    logging.info(f"Loaded {df.count()} PR records.")

    df = df.fillna({
        "additions":0,"deletions":0,"changed_files":0,
        "assignees_count":0,"commits_count":0,
        "author_association":"",
        "labels":[],"title":"","body":""
    })

    threshold=5000
    df = df.withColumn("label", when((col("additions")+col("deletions"))>threshold,1).otherwise(0))

    selected_df = df.select(
        "additions","deletions","changed_files",
        "assignees_count","commits_count",
        "author_association","labels","title","body","label"
    )

    local_dir = tempfile.mkdtemp()
    local_parquet = os.path.join(local_dir,"pr_features.parquet")
    selected_df.write.mode("overwrite").parquet(local_parquet)
    logging.info(f"Parquet => {local_parquet}")

    session = boto3.session.Session()
    s3 = session.resource("s3", endpoint_url=do_spaces_endpoint)
    bucket = s3.Bucket(do_spaces_bucket)
    prefix=f"preprocess-runs/{run_id}/"
    part_files=glob.glob(os.path.join(local_parquet,"*.parquet"))+glob.glob(os.path.join(local_parquet,"_*"))
    for fpath in part_files:
        fname=os.path.basename(fpath)
        s3_key=prefix+fname
        with open(fpath,"rb") as fp:
            bucket.put_object(Key=s3_key, Body=fp)
        logging.info(f"Uploaded {fname} to s3://{do_spaces_bucket}/{s3_key}")

    spark.stop()
    logging.info("Spark preprocess done.")

if __name__=="__main__":
    main()
