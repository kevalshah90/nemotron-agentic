# K8s Nemotron Advisor

An agentic system that uses NVIDIA Llama-3.3-Nemotron-Super-49B as the orchestrating / lead agent to monitor, analyze, and manage Kubernetes clusters autonomously. The model is deployed as an NVIDIA NIM microservice on Kubernetes.

## Architecture

The system follows a multi-agent architecture where specialized agents handle distinct responsibilities, coordinated by a central Nemotron-powered orchestrator.

```
k8s-nemotron-advisor/
├── agents/
│   ├── __init__.py
│   ├── metrics_agent.py      # Prometheus/Telemetry (The Sensors)
│   ├── k8s_api_agent.py      # K8s interactions (The Actuators)
│   └── anomaly_agent.py      # Statistical analysis (The Verification)
├── orchestrator/
│   ├── __init__.py
│   └── nemotron.py           # Nemotron NIM Logic (The Lead Agent)
├── nim/                      # NIM microservice deployment manifests
│   ├── namespace.yaml
│   ├── secret.yaml
│   ├── pvc.yaml
│   ├── deployment.yaml
│   └── service.yaml
├── k8s/                      # Advisor deployment manifests
│   ├── rbac.yaml
│   └── cronjob.yaml
├── Dockerfile
├── .env                      # API Keys (local dev only)
├── requirements.txt
└── main.py
```

## Agents

### Metrics Agent (The Sensors)
Connects to Prometheus and other telemetry sources to collect cluster metrics such as GPU power consumption, GPU utilization, and error rates.

### K8s API Agent (The Actuators)
Interfaces with the Kubernetes API to query cluster state — node resources, GPU capacity, and pod information.

### Anomaly Agent (The Verification)
Performs statistical analysis (z-score based) on collected metrics to detect anomalies and deviations from expected behavior.

## Orchestrator

### Nemotron (The Lead Agent)
Uses NVIDIA Llama-3.3-Nemotron-Super-49B (deployed as a NIM microservice) to reason over agent outputs, assess cluster health, and recommend actions. Communicates via OpenAI-compatible API.

## Requirements

### Infrastructure
- Kubernetes cluster with NVIDIA GPU Operator installed
- At least 1x NVIDIA H100-80GB or A100-80GB GPU node (for NIM deployment)
- NVIDIA device plugin for Kubernetes
- Prometheus deployed in the cluster (for metrics collection)

### Credentials
- **NGC API Key** — for pulling the NIM container image from `nvcr.io`
- **NVIDIA API Key** — (optional) only needed if using NVIDIA hosted API instead of self-hosted NIM

### Python Dependencies
- `requests`
- `numpy`
- `kubernetes`
- `python-dotenv`

## Setup

### 1. Deploy the NIM Microservice

```bash
# Create namespace
kubectl apply -f nim/namespace.yaml

# Create NGC pull secret
kubectl create secret docker-registry ngc-secret \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password=<NGC_API_KEY> \
  -n nim

# Create NGC API key secret
kubectl create secret generic ngc-api-key \
  --from-literal=NGC_API_KEY=<NGC_API_KEY> \
  -n nim

# Deploy NIM
kubectl apply -f nim/pvc.yaml
kubectl apply -f nim/deployment.yaml
kubectl apply -f nim/service.yaml
```

### 2. Deploy the Advisor Agent

```bash
# Create namespace
kubectl create namespace monitoring

# Create NVIDIA API key secret (optional, only if using hosted API)
kubectl create secret generic nemotron-secrets \
  --from-literal=NVIDIA_API_KEY=<your-key> \
  -n monitoring

# Deploy RBAC and CronJob
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/cronjob.yaml
```

### 3. Local Development

```bash
git clone https://github.com/kevalshah90/nemotron-agentic.git
cd nemotron-agentic
pip install -r requirements.txt

python main.py \
  --prometheus-url http://localhost:9090 \
  --nim-url http://localhost:8000
```

## How It Works

1. **Metrics Agent** polls Prometheus for current cluster telemetry (GPU power, utilization).
2. **Anomaly Agent** runs z-score analysis to flag statistically significant deviations.
3. **Nemotron orchestrator** receives all data, assesses cluster health, and recommends actions.
4. The cycle repeats every 5 minutes (configured via CronJob).
