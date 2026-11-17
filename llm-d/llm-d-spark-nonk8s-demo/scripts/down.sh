#!/usr/bin/env bash
cd "$(dirname "$0")/.."
docker compose --profile obs --profile model --profile router down
