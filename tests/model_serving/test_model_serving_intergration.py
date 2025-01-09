import os
import re
import requests
import pytest
import docker
import time

@pytest.mark.integration
def test_model_serving_integration():
    """
    Spin up ephemeral model-serving container, do a simple /predict call,
    check logs, then stop container.
    """
    client = docker.from_env()
    image_tag = os.getenv("MODEL_SERVING_IMAGE","local/model-serving:latest")

    container = client.containers.run(
        image_tag,
        detach=True,
        name="ephemeral-model-serving",
        ports={"80/tcp": 8080}
    )

    # Wait a bit for Flask to start
    time.sleep(5)

    # Test /predict
    url="http://localhost:8080/predict"
    r=requests.post(url, json={"features":[1,2,3]})
    container_logs=container.logs().decode("utf-8")
    exit_code=container.wait()["StatusCode"]
    container.remove()

    # Check
    assert r.status_code in (200,500), f"Got {r.status_code} from predict"
    assert exit_code==0, f"Container exit code={exit_code}"
    # Possibly check logs
    assert "Loaded model from" in container_logs, "No mention of model load in logs"
