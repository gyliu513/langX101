#!/usr/bin/env bash
# Delete the demo cluster and make sure the shared GPU is back to defaults.
set -uo pipefail
kind delete cluster --name dra
# DRA sharing configs (time-slicing / MPS) change GPU-wide settings on the
# physical GPU. They are reset when a claim is released, but a failed
# prepare can leave them behind, so double-check:
nvidia-smi --query-gpu=compute_mode --format=csv,noheader
nvidia-smi compute-policy -l
# If compute_mode is not "Default":   sudo nvidia-smi -c DEFAULT
