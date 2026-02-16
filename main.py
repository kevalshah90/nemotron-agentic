import os
import json
import argparse
from dotenv import load_dotenv
from agents import MetricsAgent, K8sAPIAgent, AnomalyDetectorAgent
from orchestrator import Nemotron

load_dotenv()

SYSTEM_PROMPT = """You are a Kubernetes cluster advisor powered by Nemotron-4 340B.
Analyze the provided cluster metrics and return a JSON object with:
- "assessment": a brief summary of cluster health
- "actions": a list of recommended actions, each with "action_type", "target", and "reason"
- "risk_level": one of "low", "medium", "high"
Respond ONLY with valid JSON."""


def run_advisor_loop(prometheus_url: str, nim_url: str):
    api_key = os.getenv("NVIDIA_API_KEY")
    brain = Nemotron(nim_url=nim_url, api_key=api_key)
    metrics_agent = MetricsAgent(prometheus_url=prometheus_url)
    anomaly_agent = AnomalyDetectorAgent()

    # 1. Collect metrics
    print("[1/4] Collecting cluster metrics...")
    power_data = metrics_agent.query_power_consumption()
    gpu_data = metrics_agent.query_gpu_utilization()

    # 2. Run anomaly detection
    print("[2/4] Running anomaly detection...")
    gpu_utils = [g["util"] for g in gpu_data.get("gpu_details", [])]
    anomaly_report = anomaly_agent.detect_power_anomalies(gpu_utils)

    # 3. Ask Nemotron to analyze and recommend
    print("[3/4] Consulting Nemotron brain...")
    context = json.dumps({
        "power": power_data,
        "gpu_utilization": gpu_data,
        "anomalies": anomaly_report
    }, indent=2)
    recommendation = brain.orchestrate(SYSTEM_PROMPT, f"Current cluster state:\n{context}")

    # 4. Output recommendation
    print("[4/4] Nemotron recommendation:")
    print(recommendation)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K8s Nemotron Advisor")
    parser.add_argument("--prometheus-url", required=True, help="Prometheus endpoint URL (e.g. http://prometheus:9090)")
    parser.add_argument("--nim-url", required=True, help="NIM microservice URL (e.g. http://nemotron-nim.default.svc:8000)")
    args = parser.parse_args()
    run_advisor_loop(args.prometheus_url, args.nim_url)
