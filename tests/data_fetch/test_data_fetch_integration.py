`import os
import re
import time
import pytest
import docker

@pytest.mark.integration
def test_data_fetch_integration():
    """
    Spins up the data-fetch container, waits for it to finish,
    then checks logs for a key message (e.g. "Data fetch complete.").
    """
    client = docker.from_env()
    image_tag = os.getenv("DATA_FETCH_IMAGE", "local/data-fetch:latest")

    container = client.containers.run(
        image_tag,
        detach=True,
        name="ephemeral-datafetch-test",
    )

    # Wait for the container to exit
    exit_code = container.wait()["StatusCode"]
    logs = container.logs().decode("utf-8")
    container.remove()

    # Simple checks
    assert exit_code == 0, f"Container exited with code {exit_code}"
    assert "Data fetch complete." in logs or "Data fetch stage complete." in logs, \
        f"Expected completion message in logs. Logs:\n{logs[:500]}..."

    # Optionally parse how many PRs were fetched, etc.
    match = re.search(r"Fetching (\d+) PRs from", logs)
    if match:
        pr_count = int(match.group(1))
        assert pr_count >= 0, "Should have fetched zero or more PRs."
`