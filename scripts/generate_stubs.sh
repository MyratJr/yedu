#!/usr/bin/env bash
set -euo pipefail

PROTO_DIR="app/proto"

echo "→ Generating Python stubs from ${PROTO_DIR}/chat.proto"

python -m grpc_tools.protoc \
  -I "${PROTO_DIR}" \
  --python_out="${PROTO_DIR}" \
  --grpc_python_out="${PROTO_DIR}" \
  "${PROTO_DIR}/chat.proto"

echo "✓ Generated:"
echo "    ${PROTO_DIR}/chat_pb2.py"
echo "    ${PROTO_DIR}/chat_pb2_grpc.py"