#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

# Quick start script for the metrics demo
# This script sets up the entire monitoring stack and starts generating metrics

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================================="
echo "🦙 Llama Stack - Tool Runtime Metrics Demo"
echo "=============================================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    echo "   Please start Docker and try again"
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Error: docker-compose is not installed"
    echo "   Please install docker-compose and try again"
    exit 1
fi

echo "✅ Docker is running"
echo ""

# Step 1: Start the monitoring stack
echo "📦 Step 1: Starting monitoring stack (OTLP, Prometheus, Grafana)..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to be healthy (30 seconds)..."
sleep 30

# Check if services are healthy
echo ""
echo "🔍 Checking service health..."
docker-compose ps

if docker-compose ps | grep -q "unhealthy"; then
    echo ""
    echo "⚠️  Warning: Some services are unhealthy"
    echo "   Check logs with: docker-compose logs"
    echo ""
    read -p "Continue anyway? (y/N): " continue_choice
    if [[ ! "$continue_choice" =~ ^[Yy]$ ]]; then
        echo "Exiting..."
        exit 1
    fi
fi

echo ""
echo "✅ All services are running"
echo ""

# Step 2: Configure environment variables
echo "🔧 Step 2: Configuring environment variables..."
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SERVICE_NAME="llama-stack-demo"
export OTEL_METRIC_EXPORT_INTERVAL="5000"

echo "   ✓ OTEL_EXPORTER_OTLP_ENDPOINT=$OTEL_EXPORTER_OTLP_ENDPOINT"
echo "   ✓ OTEL_EXPORTER_OTLP_PROTOCOL=$OTEL_EXPORTER_OTLP_PROTOCOL"
echo "   ✓ OTEL_SERVICE_NAME=$OTEL_SERVICE_NAME"
echo "   ✓ OTEL_METRIC_EXPORT_INTERVAL=$OTEL_METRIC_EXPORT_INTERVAL"
echo ""

# Step 3: Test connectivity
echo "🔗 Step 3: Testing connectivity..."

# Test OTLP endpoint
if curl -s -o /dev/null -w "%{http_code}" http://localhost:4318/v1/metrics > /dev/null; then
    echo "   ✓ OTLP Collector is reachable"
else
    echo "   ⚠️  OTLP Collector may not be ready yet"
fi

# Test Prometheus
if curl -s http://localhost:9090/-/healthy > /dev/null 2>&1; then
    echo "   ✓ Prometheus is healthy"
else
    echo "   ⚠️  Prometheus may not be ready yet"
fi

# Test Grafana
if curl -s http://localhost:3000/api/health > /dev/null 2>&1; then
    echo "   ✓ Grafana is healthy"
else
    echo "   ⚠️  Grafana may not be ready yet"
fi

echo ""

# Step 4: Open UIs
echo "🌐 Step 4: Opening UIs in browser..."
echo ""
echo "   📊 Prometheus: http://localhost:9090"
echo "   📈 Grafana:    http://localhost:3000 (admin/admin)"
echo ""

# Try to open in browser (macOS)
if command -v open &> /dev/null; then
    open http://localhost:9090 2>/dev/null || true
    sleep 2
    open http://localhost:3000 2>/dev/null || true
fi

# Step 5: Generate metrics
echo ""
echo "=============================================================="
echo "🚀 Ready to generate metrics!"
echo "=============================================================="
echo ""
echo "To start generating metrics, run:"
echo ""
echo "   export OTEL_EXPORTER_OTLP_ENDPOINT='http://localhost:4318'"
echo "   export OTEL_EXPORTER_OTLP_PROTOCOL='http/protobuf'"
echo "   export OTEL_SERVICE_NAME='llama-stack-demo'"
echo "   export OTEL_METRIC_EXPORT_INTERVAL='5000'"
echo ""
echo "   python generate_metrics.py"
echo ""
echo "Or run it now:"
read -p "Start generating metrics now? (Y/n): " generate_choice

if [[ ! "$generate_choice" =~ ^[Nn]$ ]]; then
    echo ""
    echo "🎯 Starting metrics generation..."
    echo ""
    python generate_metrics.py
else
    echo ""
    echo "=============================================================="
    echo "✅ Setup Complete!"
    echo "=============================================================="
    echo ""
    echo "Services are running:"
    echo "   - OTLP Collector: http://localhost:4318"
    echo "   - Prometheus:     http://localhost:9090"
    echo "   - Grafana:        http://localhost:3000"
    echo ""
    echo "To generate metrics:"
    echo "   export OTEL_EXPORTER_OTLP_ENDPOINT='http://localhost:4318'"
    echo "   export OTEL_EXPORTER_OTLP_PROTOCOL='http/protobuf'"
    echo "   python generate_metrics.py"
    echo ""
    echo "To stop:"
    echo "   docker-compose down"
    echo ""
fi
