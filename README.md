# K8s Nemotron Advisor

An agentic system that uses NVIDIA Nemotron-4 340B as the orchestrating / lead agent to monitor, analyze, and manage Kubernetes clusters autonomously.

## Architecture

The system follows a multi-agent architecture where specialized agents handle distinct responsibilities, coordinated by a central Nemotron-powered orchestrator.

```
k8s-nemotron-advisor/
├── agents/
│   ├── __init__.py
│   ├── metrics_agent.py      # Prometheus/Telemetry (The Sensors)
│   ├── k8s_api_agent.py      # K8s interactions (The Actuators)
│   ├── anomaly_agent.py      # Statistical analysis (The Verification)
│   └── guardian_agent.py     # Safety/Audit (The Non-negotiable layer)
├── orchestrator/
│   ├── __init__.py
│   └── nemotron.py     # Nemotron-4 340B Logic (The Lead Agent)
├── .env                      # API Keys and URLs
├── requirements.txt          # Dependencies
└── main.py                   # System entry point
```

## Agents

### Metrics Agent (The Sensors)
Connects to Prometheus and other telemetry sources to collect cluster metrics such as CPU/memory usage, pod health, network throughput, and error rates.

### K8s API Agent (The Actuators)
Interfaces with the Kubernetes API to execute actions — scaling deployments, restarting pods, applying resource limits, and querying cluster state.

### Anomaly Agent (The Verification)
Performs statistical analysis on collected metrics to detect anomalies, trends, and deviations from expected behavior before actions are taken.

### Guardian Agent (The Non-negotiable Layer)
Enforces safety policies and audit controls. Every proposed action passes through this agent to prevent destructive operations and maintain compliance.

## Orchestrator

### Nemotron Brain (The Lead Agent)
Uses Nemotron-4 340B to reason over agent outputs, formulate plans, and coordinate the agent pipeline. It receives metrics, identifies issues, proposes actions, validates them through the anomaly and guardian agents, and then delegates execution to the K8s API agent.

## Setup

1. Clone the repository:
   ```bash
   git clone <repo-url>
   cd k8s-nemotron-advisor
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables in `.env`:
   ```
   NEMOTRON_API_KEY=<your-api-key>
   PROMETHEUS_URL=<your-prometheus-endpoint>
   K8S_CLUSTER_URL=<your-cluster-endpoint>
   ```

4. Run the system:
   ```bash
   python main.py
   ```

## How It Works

1. **Metrics Agent** polls Prometheus for current cluster telemetry.
2. **Nemotron Brain** analyzes the metrics and identifies potential issues or optimization opportunities.
3. **Anomaly Agent** validates whether the identified issues are statistically significant.
4. **Nemotron Brain** formulates an action plan (e.g., scale up a deployment).
5. **Guardian Agent** reviews the plan against safety policies and approves or rejects it.
6. **K8s API Agent** executes the approved actions on the cluster.
7. The cycle repeats continuously.