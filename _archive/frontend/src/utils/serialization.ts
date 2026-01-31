
// FIXED: Extracted from websocketService.ts - Deserialize raw WS/backend data
export function deserializeNodeData(rawNode: any): any {
  const node = { ...rawNode };
  // Enums (str → upper str for store)
  const enumFields = ['status', 'task_type', 'node_type'];
  enumFields.forEach(field => {
    if (field in node && typeof node[field] === 'string') {
      node[field] = node[field].toUpperCase();
    }
  });
  // Timestamps (ISO str → Date)
  const tsFields = ['timestamp_created', 'timestamp_updated', 'timestamp_completed'];
  tsFields.forEach(field => {
    if (field in node && typeof node[field] === 'string') {
      try {
        node[field] = new Date(node[field]);
      } catch {
        node[field] = null;
      }
    }
  });
  // Recurse nested (aux_data, execution_details, full_result)
  if ('aux_data' in node && typeof node.aux_data === 'object') {
    node.aux_data = deserializeNodeData(node.aux_data);
  }
  if ('execution_details' in node && typeof node.execution_details === 'object') {
    node.execution_details = deserializeNodeData(node.execution_details);
  }
  if ('full_result' in node && typeof node.full_result === 'object') {
    node.full_result = deserializeNodeData(node.full_result);
  }
  return node;
}

export function deserializeState(rawData: any): any {
  const data = { ...rawData };
  if ('all_nodes' in data) {
    data.all_nodes = {
      ...data.all_nodes,
      ...Object.fromEntries(
        Object.entries(data.all_nodes).map(([id, node]: [string, any]) => [id, deserializeNodeData(node)])
      )
    };
  }
  // Recurse graphs/other if needed
  if ('graphs' in data && typeof data.graphs === 'object') {
    data.graphs = { ...data.graphs };  // Shallow for now
  }
  return data;
}
