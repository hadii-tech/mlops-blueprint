from locust import HttpUser, task, between
import random

class ModelServingPerfUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def predict_random(self):
        features = [random.random() for _ in range(10)]
        self.client.post("/predict", json={"features": features})
        