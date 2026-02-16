from kubernetes import client, config
from typing import Dict, Any

class K8sAPIAgent:
    def __init__(self):
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()
        self.v1 = client.CoreV1Api()

    def get_node_resources(self) -> Dict[str, Any]:
        nodes = self.v1.list_node()
        node_info = []
        for node in nodes.items:
            node_info.append({
                'name': node.metadata.name,
                'capacity_gpus': int(node.status.capacity.get('nvidia.com/gpu', '0')),
                'allocatable_cpu': node.status.allocatable.get('cpu', '0')
            })
        return {'total_nodes': len(node_info), 'nodes': node_info}