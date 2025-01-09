import logging
import os
import datetime
from pymongo import MongoClient, UpdateOne
from github import Github
import hvac

logging.basicConfig(level=logging.INFO)

def get_vault_client():
    vault_addr = os.getenv("VAULT_ADDR","http://vault.vault.svc.cluster.local:8200")
    vault_path_auth = os.getenv("VAULT_PATH_AUTH","auth/kubernetes/login")
    vault_role = os.getenv("VAULT_ROLE","mlops-datafetch")
    # Pod's service account token
    with open("/var/run/secrets/kubernetes.io/serviceaccount/token","r") as f:
        sa_token = f.read()
    client = hvac.Client(url=vault_addr)
    client.auth_kubernetes(role=vault_role, jwt=sa_token, mount_point=vault_path_auth.replace("/login",""))
    if not client.is_authenticated():
        raise Exception("Vault auth failed for data-fetch.")
    return client

def main():
    vault_secret_path = os.getenv("VAULT_SECRET_PATH","secret/data/mlops/base/data-fetch")
    vault_client = get_vault_client()
    # For Vault KV v2
    resp = vault_client.secrets.kv.v2.read_secret_version(path=vault_secret_path.replace("secret/data/",""))
    secrets = resp["data"]["data"]

    mongo_uri = secrets["mongo_uri"]
    mongo_db = secrets["mongo_db"]
    mongo_coll = secrets["mongo_collection"]
    github_token = secrets["github_token"]

    from pymongo import MongoClient
    c = MongoClient(mongo_uri)
    db = c[mongo_db]
    coll = db[mongo_coll]

    gh = Github(github_token)

    query = "stars:>100"
    result = gh.search_repositories(query=query, sort="stars", order="desc")
    max_repos = 10
    repos_processed = 0

    for repo in result:
        if repos_processed >= max_repos:
            break
        repos_processed += 1
        pulls = repo.get_pulls(state='all')
        logging.info(f"Fetching {pulls.totalCount} PRs from {repo.full_name}")

        bulk_ops = []
        for pr in pulls:
            pr_updated = pr.updated_at or datetime.datetime(1970,1,1)
            existing = coll.find_one({"pr_id": pr.id}, {"updated_at":1})
            if existing and existing.get("updated_at") and existing["updated_at"] >= pr_updated:
                continue

            pr_data = {
                "repo_name": repo.full_name,
                "pr_id": pr.id,
                "number": pr.number,
                "additions": pr.additions,
                "deletions": pr.deletions,
                "changed_files": pr.changed_files,
                "assignees_count": len(pr.assignees),
                "commits_count": pr.commits,
                "author_association": pr.author_association or "",
                "labels": [lab.name for lab in pr.labels],
                "title": pr.title or "",
                "body": pr.body or "",
                "created_at": pr.created_at,
                "merged_at": pr.merged_at,
                "updated_at": pr_updated,
                "closed_at": pr.closed_at,
                "state": pr.state
            }
            bulk_ops.append(UpdateOne({"pr_id": pr.id}, {"$set": pr_data}, upsert=True))

        if bulk_ops:
            try:
                coll.bulk_write(bulk_ops, ordered=False)
                logging.info(f"Bulk upserted {len(bulk_ops)} PRs for {repo.full_name}")
            except Exception as e:
                logging.error(f"Error bulk upserting {repo.full_name}: {e}")

    logging.info("Data fetch complete.")

if __name__=="__main__":
    main()
    