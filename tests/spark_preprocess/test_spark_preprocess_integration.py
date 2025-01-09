import os
import time
import re
import pytest
import docker

@pytest.mark.integration
def test_spark_preprocess_integration():
    """
    Spins up spark-preprocess container ephemeral,
    checks logs for success line like "Spark preprocess complete."
    """
    client = docker.from_env()
    image_tag = os.getenv("SPARK_PREPROCESS_IMAGE", "local/spark-preprocess:latest")

    container = client.containers.run(
        image_tag,
        detach=True,
        name="ephemeral-spark-preprocess-test"
    )

    exit_code = container.wait()["StatusCode"]
    logs = container.logs().decode("utf-8")
    container.remove()

    assert exit_code == 0, f"Spark Preprocess container exit code={exit_code}"
    # Look for "Spark preprocess complete." in logs or "Data written locally to..."
    assert "Spark preprocess complete." in logs or "Spark Preprocess stage complete." in logs, \
        f"Didn't see success message in Spark logs:\n{logs[:500]}"

    # Possibly parse how many PR records were loaded
    match = re.search(r"Loaded (\d+) PR records", logs)
    if match:
        count = int(match.group(1))
        assert count >= 0

