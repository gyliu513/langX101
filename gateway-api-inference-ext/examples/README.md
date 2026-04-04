# Scheduling Framework Developer Guide

This directory contains working examples that demonstrate how to extend the
Gateway API Inference Extension (GIE) scheduling framework with custom
out-of-tree plugins and how to build a custom EPP binary.

For a real-world out-of-tree project built on this framework, see
[llm-d-inference-scheduler](https://github.com/llm-d/llm-d-inference-scheduler).

## Directory Layout

```
examples/
├── scheduler/                           # Example 1: Scheduler plugin development
│   ├── main.go                          # Standalone demo — runs locally, no cluster needed
│   └── plugins/
│       ├── register.go                  # RegisterAllPlugins() — central registration
│       ├── filter/
│       │   └── model_affinity.go        # Custom Filter plugin
│       ├── scorer/
│       │   └── least_loaded.go          # Custom Scorer plugin
│       └── profile/
│           └── simple_profile_handler.go # Custom ProfileHandler plugin
├── custom-epp/                          # Example 2: Custom EPP binary
│   └── main.go                          # Embeds custom plugins into the real EPP
└── README.md                            # This file
```

## Quick Start

**Run the scheduler demo** (no cluster required):

```bash
make run-example EXAMPLE=scheduler
```

**Build a custom EPP binary** (requires a Kubernetes cluster to run):

```bash
go build -o custom-epp ./examples/custom-epp/
```

## Scheduling Architecture

The scheduler uses a **Filter → Score → Pick** pipeline, driven by a
**ProfileHandler**:

```
                    ┌──────────────────────────────────────────────┐
                    │              ProfileHandler                  │
                    │  Pick(): which profiles to run               │
                    │  ProcessResults(): choose primary profile    │
                    └──────────────┬───────────────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────────────┐
                    │           SchedulerProfile                   │
                    │                                              │
                    │  ┌─────────┐  ┌──────────┐  ┌────────────┐  │
                    │  │ Filter  │→ │  Scorer   │→ │   Picker   │  │
                    │  │ (N个)   │  │ (N个,带权) │  │  (1个)     │  │
                    │  └─────────┘  └──────────┘  └────────────┘  │
                    └──────────────────────────────────────────────┘
```

- **Filter** — removes endpoints that should not receive the request.
- **Scorer** — assigns a score in `[0, 1]` to each surviving endpoint.
  Scores are multiplied by the scorer's weight and summed.
- **Picker** — selects the final endpoint(s) from the scored list.
- **ProfileHandler** — controls which profiles run and aggregates results.

## How to Write a Custom Plugin

### Step 1: Implement the Plugin Interface

Every plugin must satisfy `plugin.Plugin` by implementing `TypedName()`:

```go
import plugin "sigs.k8s.io/gateway-api-inference-extension/pkg/epp/framework/interface/plugin"

type MyPlugin struct {
    typedName plugin.TypedName
}

func (p *MyPlugin) TypedName() plugin.TypedName { return p.typedName }
```

### Step 2: Implement the Scheduling Interface

Choose which extension point your plugin targets:

#### Filter

```go
import sched "sigs.k8s.io/gateway-api-inference-extension/pkg/epp/framework/interface/scheduling"

// Drop endpoints that should not serve this request.
func (f *MyFilter) Filter(ctx context.Context, cycleState *sched.CycleState,
    request *sched.LLMRequest, endpoints []sched.Endpoint) []sched.Endpoint {
    // return a subset of endpoints
}
```

See [`plugins/filter/model_affinity.go`](scheduler/plugins/filter/model_affinity.go) for a complete example.

#### Scorer

```go
// Category tells the framework what kind of preference this scorer applies.
func (s *MyScorer) Category() sched.ScorerCategory {
    return sched.Distribution  // or sched.Affinity, sched.Balance
}

// Score returns a value in [0, 1] for each endpoint. Higher is better.
func (s *MyScorer) Score(ctx context.Context, cycleState *sched.CycleState,
    request *sched.LLMRequest, endpoints []sched.Endpoint) map[sched.Endpoint]float64 {
    // return scores
}
```

See [`plugins/scorer/least_loaded.go`](scheduler/plugins/scorer/least_loaded.go) for a complete example.

#### ProfileHandler

```go
// Pick selects which profiles to run. Return empty map to stop the loop.
func (h *MyHandler) Pick(ctx context.Context, cycleState *sched.CycleState,
    request *sched.LLMRequest, profiles map[string]sched.SchedulerProfile,
    profileResults map[string]*sched.ProfileRunResult) map[string]sched.SchedulerProfile {
    // return profiles to execute
}

// ProcessResults chooses the primary profile after all profiles finish.
func (h *MyHandler) ProcessResults(ctx context.Context, cycleState *sched.CycleState,
    request *sched.LLMRequest,
    profileResults map[string]*sched.ProfileRunResult) (*sched.SchedulingResult, error) {
    // return final result
}
```

See [`plugins/profile/simple_profile_handler.go`](scheduler/plugins/profile/simple_profile_handler.go) for a complete example.

### Step 3: Provide a FactoryFunc

The config loader uses a `FactoryFunc` to instantiate plugins from YAML:

```go
func Factory(name string, rawParameters json.RawMessage, handle plugin.Handle) (plugin.Plugin, error) {
    p := New()
    p.typedName.Name = name
    // Optionally parse rawParameters for plugin-specific config
    return p, nil
}
```

### Step 4: Register in RegisterAllPlugins()

Add your plugin to the central registration function:

```go
// plugins/register.go
func RegisterAllPlugins() {
    plugin.Register("my-filter-type",  filter.Factory)
    plugin.Register("my-scorer-type",  scorer.Factory)
    plugin.Register("my-handler-type", profile.Factory)
}
```

## How to Build a Custom EPP

A custom EPP is deployed alongside (or instead of) the default EPP. Each
`InferencePool` independently references whichever EPP it needs:

```
                         ┌───────────────┐
         User Request ──►│    Envoy      │
                         │  (ext-proc)   │
                         └───┬───────┬───┘
                             │       │
                   ┌─────────▼──┐ ┌──▼───────────┐
                   │InferencePool│ │InferencePool │
                   │  pool-a     │ │  pool-b      │
                   │  ext: epp-a │ │  ext: epp-b  │
                   └──────┬──────┘ └──────┬───────┘
                          │               │
                   ┌──────▼──────┐ ┌──────▼───────┐
                   │EPP (upstream)│ │ EPP (custom) │
                   │ built-in    │ │ out-of-tree  │
                   │ plugins     │ │ plugins      │
                   └──────┬──────┘ └──────┬───────┘
                          │               │
                   ┌──────▼──────┐ ┌──────▼───────┐
                   │  vLLM pods  │ │  vLLM pods   │
                   └─────────────┘ └──────────────┘
```

**How it works:** Envoy receives a user request and invokes the ext-proc
callback. The Gateway API `HTTPRoute` maps the request path to an
`InferencePool`. Each `InferencePool` has an `extensionRef` field that points
to a specific EPP's Kubernetes Service. This is how routing to different EPPs
is decided — it is purely a matter of which `InferencePool` the request
matches, and which EPP Service that pool references. Multiple EPP deployments
can coexist in the same cluster, each serving different pools with different
scheduling strategies.

A custom EPP binary is a standard Go program that registers your plugins and
then starts the upstream EPP Runner. This is the same pattern used by
[llm-d-inference-scheduler](https://github.com/llm-d/llm-d-inference-scheduler/blob/main/cmd/epp/main.go).

### In-tree (this repo)

See [`custom-epp/main.go`](custom-epp/main.go):

```go
import (
    "sigs.k8s.io/gateway-api-inference-extension/cmd/epp/runner"
    "sigs.k8s.io/gateway-api-inference-extension/examples/scheduler/plugins"
)

func main() {
    plugins.RegisterAllPlugins()
    runner.NewRunner().Run(ctrl.SetupSignalHandler())
}
```

### Out-of-tree (your own repo)

Create a new Go module that depends on gateway-api-inference-extension:

```
my-inference-scheduler/
├── go.mod                    # require sigs.k8s.io/gateway-api-inference-extension
├── cmd/epp/main.go           # Your entry point
├── pkg/plugins/
│   ├── register.go           # RegisterAllPlugins()
│   ├── filter/
│   ├── scorer/
│   └── profile/
├── config.yaml               # EndpointPickerConfig referencing your plugins
└── Dockerfile
```

Your `cmd/epp/main.go`:

```go
package main

import (
    "os"
    ctrl "sigs.k8s.io/controller-runtime"
    "sigs.k8s.io/gateway-api-inference-extension/cmd/epp/runner"
    "github.com/my-org/my-inference-scheduler/pkg/plugins"
)

func main() {
    plugins.RegisterAllPlugins()
    if err := runner.NewRunner().Run(ctrl.SetupSignalHandler()); err != nil {
        os.Exit(1)
    }
}
```

Your `go.mod`:

```
module github.com/my-org/my-inference-scheduler

require sigs.k8s.io/gateway-api-inference-extension v1.4.0
```

### YAML Configuration

The custom EPP loads an `EndpointPickerConfig` that can reference both
built-in and custom plugins:

```yaml
apiVersion: inference.networking.x-k8s.io/v1alpha1
kind: EndpointPickerConfig
plugins:
  # Custom plugins (registered by your RegisterAllPlugins)
  - type: model-affinity-filter
    name: my-filter
  - type: least-loaded-scorer
    name: my-scorer
  - type: logging-profile-handler
    name: my-handler
  # Built-in plugins (registered by the Runner)
  - type: max-score-picker
    name: picker
schedulingProfiles:
  - name: default
    plugins:
      - pluginRef: my-filter
      - pluginRef: my-scorer
        weight: 2
      - pluginRef: picker
profileHandler: my-handler
```

### Deploying

Build and deploy to your Kubernetes cluster, then point an `InferencePool`
at your custom EPP:

```yaml
apiVersion: inference.networking.x-k8s.io/v1alpha2
kind: InferencePool
metadata:
  name: my-pool
spec:
  targetPortNumber: 8000
  selector:
    app: vllm
  extensionRef:
    name: my-custom-epp    # Your EPP's Service name
```

Multiple EPP deployments can coexist in a cluster — each `InferencePool`
independently references whichever EPP it needs via `extensionRef`.
