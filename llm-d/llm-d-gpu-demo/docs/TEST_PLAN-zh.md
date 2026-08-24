# llm-d GPU Demo —— 详细测试计划

*[English](TEST_PLAN.md)*

配合 [`../README-zh.md`](../README-zh.md) 使用。本文档假设你**完全没有背景知
识**——如果你已经按 README 的安装步骤跑完、集群是好的,下面每个测试用例都可
以照着原样执行,得到相同(或等价)的结果。

**格式说明:** 每个测试用例都有明确的目的、前置条件,以及一串编号的步骤。每
一步都写明确切要执行的**命令**(输入)、这次运行**真实抓到的输出**、以及这个
输出**意味着什么、为什么这一步重要**的解释。**本文档里的每个测试用例都标了
[LIVE],都是 2026-08-24 针对 README 里描述的那次运行真实执行过的**——没有一
条是示例、预测或者没跑过的。有几个用例即使正确执行了,结果也是负面的;这些结
果会如实报告、附带根因分析,而不是藏起来。

全文共用的变量(每个 shell 会话设一次即可):

```console
export GWIP=$(kubectl get svc llm-d-inference-gateway -n llm-d -o jsonpath='{.spec.clusterIP}')
export DGX_HOST=192.168.1.112
export DGX_USER=lgy
export MODEL=Qwen/Qwen2.5-1.5B-Instruct
```

---

## 第 1 组 —— TC-GPU-*:DGX Spark 上 vLLM 的健康状况(真实硬件)

### TC-GPU-01 —— vLLM server 健康检查端点 **[LIVE]**

**目的:** 确认 DGX Spark 上真实的 vLLM 进程能正常响应健康检查。
**组件:** DGX Spark 上的 `vllm-gpu-0` 容器。
**前置条件:** README §3 步骤 1 已完成(vLLM 容器已在运行)。

**测试步骤:**

1. **从你的工作机向 DGX Spark 暴露出来的 8000 端口发一个健康检查请求。**
   - 命令:
     ```console
     curl -sS -m 5 -o /dev/null -w "http=%{http_code}\n" http://$DGX_HOST:8000/health
     ```
   - 输出:`http=200`
   - 解释:vLLM 的 OpenAI 兼容 server 把 `/health` 暴露为一个轻量存活检
     查,一旦引擎加载完成、可以接请求了,就返回空 body 的 `200 OK`。
     `-m 5` 把请求超时限制在 5 秒,server 卡住时能快速失败,而不是让测试脚
     本一直挂着。

2. **通过 `/v1/models` 确认模型身份。**
   - 命令:
     ```console
     curl -sS http://$DGX_HOST:8000/v1/models | python3 -c "import sys,json;print(json.load(sys.stdin)['data'][0]['id'])"
     ```
   - 输出:`Qwen/Qwen2.5-1.5B-Instruct`
   - 解释:`/v1/models` 是 OpenAI API 里列模型的端点;这一步确认服务器加载
     的确实是你要的模型(而不是复制粘贴命令时手滑,悄悄起了另一个模型)。

**结论:** PASS —— 两项检查都得到了预期的确切值。

---

### TC-GPU-02 —— 真实的对话补全返回连贯文本 **[LIVE]**

**目的:** 确认模型确实在 GPU 上真实生成了 token,而不只是能应付健康检查。
**前置条件:** TC-GPU-01 通过。

**测试步骤:**

1. **发一个真实的对话补全请求。**
   - 命令:
     ```console
     curl -sS -X POST http://$DGX_HOST:8000/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello in 5 words\"}],\"max_tokens\":20}"
     ```
   - 输出:
     ```json
     {"id":"chatcmpl-8d3fad5343e92b77","object":"chat.completion","created":1787589712,
      "model":"Qwen/Qwen2.5-1.5B-Instruct",
      "choices":[{"index":0,"message":{"role":"assistant","content":"Hello! How can I assist you today?"},"finish_reason":"stop"}],
      "usage":{"prompt_tokens":31,"total_tokens":33,"completion_tokens":2}}
     ```
   - 解释:`choices[0].message.content` 是模型真实生成的、语法通顺的文本——
     不是把输入原样回显,也不是写死的字符串。`usage` 块精确记录了消耗的
     token 数:`prompt_tokens=31` 包含了 chat 模板本身的 system/role 格式
     开销(你 6 个词的 prompt 本身远没这么多 token);`completion_tokens` 每
     次跑都会不一样,因为采样没有固定种子。

**结论:** PASS —— `content` 非空且语法正确;`completion_tokens` ≤ 请求的
`max_tokens`。

---

### TC-GPU-03 —— GPU 进程在 `nvidia-smi` 里可见 **[LIVE]**

**目的:** 证明 TC-GPU-02 那个请求确实是 GPU 处理的,不是悄悄退回了 CPU。

**测试步骤:**

1. **SSH 到 DGX Spark,跑 `nvidia-smi`。**
   - 命令:`ssh $DGX_USER@$DGX_HOST nvidia-smi`
   - 输出(Processes 表格):
     ```
     |    0   N/A  N/A         1550079      C   VLLM::EngineCore              4809MiB |
     |    0   N/A  N/A            3341      G   /usr/lib/xorg/Xorg               97MiB |
     |    0   N/A  N/A            3730      G   /usr/bin/gnome-shell            126MiB |
     ```
   - 解释:`VLLM::EngineCore` 是 vLLM 自己给推理引擎子进程取的进程名;它出
     现在 `nvidia-smi` 的进程表里(而且真的占用了显存,这里是 4809 MiB),
     这是"CUDA kernel 真的在这块 GPU 上跑"的铁证。`Xorg`/`gnome-shell` 那
     两行是桌面环境自己的 GPU 占用——和这个无关,只是因为共享同一块 GPU 才
     会看到。

**结论:** PASS。

---

### TC-GPU-04 —— GPU 显存预算符合预期 **[LIVE]**

**目的:** 确认 vLLM 的实际显存占用没有超出你配置的 `--gpu-memory-utilization`
预算。

**测试步骤:**

1. **读 vLLM 自己启动日志里的显存记账。**
   - 命令:
     ```console
     ssh $DGX_USER@$DGX_HOST 'docker logs vllm-gpu-0 2>&1 | grep -E "Model loading took|Available KV cache|GPU KV cache size"'
     ```
   - 输出:
     ```
     (EngineCore pid=258) INFO gpu_model_runner.py:4879 Model loading took 2.89 GiB memory and 60.297843 seconds
     (EngineCore pid=258) INFO gpu_worker.py:440 Available KV cache memory: 0.56 GiB
     (EngineCore pid=258) INFO kv_cache_utils.py:1708 GPU KV cache size: 20,992 tokens
     ```
   - 解释:vLLM 精确记录了它把预算分给了模型权重(2.89 GiB)和 KV cache
     (0.56 GiB),合计 3.45 GiB——远低于当时会话里配置的
     0.04 × 130.667 GB ≈ 5.23 GB 预算(这个默认值后来因为一次 OOM 调低到了
     0.03,见 TC-GPU-05)。20,992 个 token 的 KV cache 容量,按
     block-size 64 算,相当于所有并发请求总共可用 20992/64 ≈ 328 个块。

**结论:** PASS —— 实际占用 3.45 GiB ≤ 5.23 GB 预算。

---

### TC-GPU-05 —— 显存紧张情况下起第二个 replica **[LIVE —— 完整事故记录,共 3 次尝试]**

**目的:** 确定在这台共享的 DGX Spark 上,能否让第二个真实 GPU replica
(`vllm-gpu-1`)和 `vllm-gpu-0` 同时跑,并搞清楚跑不起来时的失败模式。
**说明:** 这个用例的"结果"本身就是发现——它在整个会话过程中分了三次独立尝
试,不是一次干净的 pass/fail。

**测试步骤:**

1. **第 1 次尝试,会话刚开始时。** 起第二个 replica 之前先查空闲显存。
   - 命令:
     ```console
     ssh $DGX_USER@$DGX_HOST 'docker run --rm --gpus all --ipc=host nvcr.io/nvidia/vllm:26.05-py3 python3 -c "import torch; print(torch.cuda.mem_get_info())"'
     ```
   - 输出(`vllm-gpu-0` 已在运行时):`(1128435712, 130667180032)`——总共
     130.67 GB,空闲 1.13 GB。
   - 解释:`torch.cuda.mem_get_info()` 返回 `(空闲字节数, 总字节数)`。
     1.13 GB 的空闲量,连第二个 replica 单是权重(Qwen2.5-1.5B 权重本身就
     要约 2.9 GiB)都装不下——这次尝试直接跳过,判定必然失败。

2. **第 2 次尝试,会话中段重试。** 这次空闲显存恰好高了很多(ComfyUI 自己
   的占用暂时降下去了)。两个 replica 一起起。
   - 命令(第 2 个 replica,和 `vllm-gpu-0` 同一套模式,但端口换成
     8001/5557):
     ```console
     ssh $DGX_USER@$DGX_HOST "docker run -d --gpus all --ipc=host --name vllm-gpu-1 \
       -p 8001:8001 -p 5557:5557 nvcr.io/nvidia/vllm:26.05-py3 \
       vllm serve $MODEL --port 8001 --block-size 64 --gpu-memory-utilization 0.04 \
       --max-model-len 4096 --enforce-eager \
       --kv-events-config '{\"enable_kv_cache_events\":true,\"publisher\":\"zmq\",\"endpoint\":\"tcp://*:5557\",\"topic\":\"kv@vllm-gpu-1:8001@$MODEL\"}'"
     ```
   - 输出:
     ```console
     $ ssh $DGX_USER@$DGX_HOST 'docker logs vllm-gpu-0 2>&1 | tail -1; docker logs vllm-gpu-1 2>&1 | tail -1'
     INFO:     Application startup complete.
     INFO:     Application startup complete.
     ```
   - 解释:**两个** replica 都各自报告了 `Application startup complete`——
     这是本次会话里第一次真的让 2 个真实 GPU replica 同时跑起来。

3. **约 2 分钟后,没有任何外部动作,再查一次容器状态。**
   - 命令:`ssh $DGX_USER@$DGX_HOST 'docker ps -a --filter name=vllm-gpu'`
   - 输出:
     ```
     vllm-gpu-1   Up 2 minutes
     vllm-gpu-0   Exited (1) 3 minutes ago
     ```
   - 命令:`ssh $DGX_USER@$DGX_HOST 'docker logs vllm-gpu-0 2>&1 | tail -3'`
   - 输出:
     ```
     ValueError: No available memory for the cache blocks. Try increasing `gpu_memory_utilization`...
     RuntimeError: Engine core initialization failed. See root cause above. Failed core proc(s): {}
     ```
   - 解释:`vllm-gpu-0` 自己崩溃了,没有对它执行任何外部命令。根因:当时
     `nvidia-smi` 显示 ComfyUI 进程自己的显存占用从约 14 GiB 涨到了约
     28 GiB——同一块共享 GPU 上一个不相关的进程,把两个 vLLM 进程挤得够
     呛,其中一个失去了自己的显存预留,重新初始化时失败了。

4. **第 3 次尝试,用会话开始时那个能用的 0.04 预算,只跑单个 replica 重
   试。**
   - 命令:和 TC-GPU-01 设置一样的 `docker run`,`--gpu-memory-utilization 0.04`。
   - 输出:同样的 `ValueError: No available memory for the cache blocks` 错
     误,这次**只有一个** replica 在跑(没有第二个 vLLM 进程来抢)。
   - 解释:证实失败的门槛是跟着 ComfyUI 的负载走的,不是跟 replica 数量
     走——就连一个之前能用的预算,单个 replica 后来也可能纯粹因为"box 上
     的*另一个*进程涨了"而失败。

5. **恢复:调低预算,重新部署。**
   - 命令:同样的 `docker run`,`--gpu-memory-utilization 0.03`(约 3.9 GB)。
   - 输出:`Application startup complete.`——在会话剩下的时间里一直稳定,
     后续好几个用例(TC-BRIDGE-05、TC-NEG-01)反复停止/重启它,都验证过。
   - 解释:这个发现之后,demo 的默认值在 `gpu-node/deploy-vllm.sh` 里从
     0.04 永久调低到了 0.03。

**结论:** 在这台硬件上,**2 个真实 replica 是可以做到的**——不是原理上被
彻底堵死,这推翻了同一个 demo 里更早的一条假设("不可能")。但它**不能按需
可靠复现**:共享机器上的显存余量,会独立于本 demo 能控制的一切因素而波动,一
个正在运行的 replica 随时可能被硬崩溃挤掉(不是优雅降级)。**结论:PASS
(带保留条件)**——把这两条发现都当作"记录在案的事实",而不是"稳定的保
证"。

---

### TC-GPU-06 —— 节点本地的 ZMQ KV-events 发布者启动成功 **[LIVE]**

**目的:** 确认 vLLM 确实启动了 KV-cache 感知路由所依赖的 ZMQ 发布线程。

**测试步骤:**

1. **在 vLLM 启动日志里 grep 发布线程的消息。**
   - 命令:`ssh $DGX_USER@$DGX_HOST 'docker logs vllm-gpu-0 2>&1 | grep kv_events'`
   - 输出:`(EngineCore pid=258) INFO kv_events.py:329 Starting ZMQ publisher thread`
   - 解释:只有 `--kv-events-config` 里 `enable_kv_cache_events: true` 被正
     确解析时才会出现这一行。如果忘了带这个 flag(或者 JSON 打错字),
     vLLM 照样能正常启动,但这一行永远不会出现——这是一种"沉默失败"模
     式,值得专门检查一下,而不是想当然认为它生效了。

**结论:** PASS。

---

## 第 2 组 —— TC-BRIDGE-*:proxy Pod 的正确性

### TC-BRIDGE-01 —— proxy Pod 只有在 DGX 后端可达时才变成 Ready **[LIVE]**

**目的:** 确认 `gpu-vllm-proxy` Pod 的 readiness 状态真实反映了 DGX 后端是
否可达(而不只是"容器进程起来了"）。
**前置条件:** README §3 步骤 6 已完成。

**测试步骤:**

1. **应用 proxy Pod 的清单。**
   - 命令:`kubectl apply -f manifests/optional/gpu-proxy/gpu-vllm-proxy.yaml`
   - 输出:`deployment.apps/gpu-vllm-proxy created` / `podmonitor.monitoring.coreos.com/gpu-vllm-proxy created`

2. **观察 Pod 变成 2/2 Ready。**
   - 命令:`kubectl get pods -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing -o wide`
   - 输出:
     ```
     NAME                              READY   STATUS    RESTARTS   AGE   IP
     gpu-vllm-proxy-65c98887dd-ltd6k   2/2     Running   0          23s   10.244.0.9
     ```
   - 解释:`2/2` 意味着**两个**容器的 readiness probe 都通过了——
     `http-proxy` 的探针会真的通过 socat 隧道向 DGX Spark 发一个
     `GET /health`,所以这里的 `2/2` 是一次真实的端到端可达性检查,不只
     是"容器进程在跑"。

**结论:** PASS —— apply 之后约 23 秒就到了 `2/2`。

---

### TC-BRIDGE-02 —— HTTP 透传返回结构一致的响应 **[LIVE]**

**目的:** 确认 socat 隧道不会破坏或改变 HTTP 流量。

**测试步骤:**

1. **在集群内部,把 TC-GPU-02 那个直接打到 DGX 的请求,改成通过 proxy Pod
   的 IP 发一遍。**
   - 命令:
     ```console
     PODIP=$(kubectl get pod -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing -o jsonpath='{.items[0].status.podIP}')
     kubectl run trig2 --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -X POST http://$PODIP:8000/v1/chat/completions -H 'Content-Type: application/json' \
       -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"max_tokens\":10}"
     ```
   - 输出:
     ```json
     {"id":"chatcmpl-96cf154a307c70a5","object":"chat.completion", ...,
      "choices":[{"message":{"content":"Hello! How can I assist you today?"}, "finish_reason":"stop"}], ...}
     ```
   - 解释:这是一个完整、合法的 OpenAI 对话补全 JSON 对象——和 TC-GPU-02
     直接打 DGX 得到的 schema 一模一样。`socat` 是在原始 TCP 字节层面工
     作、对协议毫无感知的,所以只要 JSON 能正常解析、schema 完整,就证明隧
     道是透明的。

**结论:** PASS。

---

### TC-BRIDGE-03 —— ZMQ 透传:EPP 的订阅者通过隧道连上了 **[LIVE]**

**目的:** 确认*第二个* socat 容器(`kv-proxy`,5556 端口)也正确做了隧道转
发——这次传的是二进制协议(ZMTP),不是 HTTP。
**前置条件:** README §3 步骤 7 已完成(EPP 已安装)。

**测试步骤:**

1. **在 EPP 自己的日志里 grep 它的 ZMQ 订阅连接。**
   - 命令:`kubectl logs -n llm-d deploy/llm-d-epp -c epp | grep zmq-subscriber`
   - 输出:
     ```json
     {"level":"info","logger":"zmq-subscriber","msg":"Connected subscriber socket","endpoint":"tcp://10.244.0.9:5556"}
     ```
   - 解释:这里的 `10.244.0.9` 是 **proxy Pod** 的集群 IP,不是 DGX Spark
     的 `192.168.1.112`。这是关键证据,证明 EPP 是在跟集群内的 proxy 通
     信(符合 README §1.1 里 InferencePool 按 Pod 选择的设计要求),而这
     个 proxy 又负责把流量转发给另一头真实的 DGX 进程。

**结论:** PASS。

---

### TC-BRIDGE-04 —— ZMQ 隧道断开后能自愈重连 **[LIVE,顺带观察到的]**

**目的:** 确认如果 EPP 到 proxy 的底层 TCP 连接断了(这次是真实发生的,不是
为了测试专门制造的),EPP 的 ZMQ 客户端能自己恢复。

**测试步骤:**

1. **在整个会话过程中持续 tail EPP 的 zmq-subscriber 日志。**
   - 命令:`kubectl logs -n llm-d deploy/llm-d-epp -c epp -f | grep zmq-subscriber`
   - 输出(真实序列,初次连上后约 8 分钟):
     ```json
     {"level":"error","msg":"Failed to receive message from zmq subscriber","endpoint":"tcp://10.244.0.9:5556","error":"EOF"}
     {"level":"info","msg":"retrying zmq-subscriber"}
     {"level":"info","msg":"Connected subscriber socket","endpoint":"tcp://10.244.0.9:5556"}
     ```
   - 解释:连接断了(`EOF`——对端关闭了连接,很可能是局域网这一跳上
     socat/网络的一次短暂抖动),EPP 的客户端库**自己**重试并重连成功,没
     有任何人工介入,对路由也没有可见影响(不需要动 InferencePool)。约
     8 分钟一次空闲连接才断一次,这个频率是健康的;如果你看到几秒钟就断
     一次,那就是局域网链路或者 proxy 本身不稳定的信号,值得单独排查。

**结论:** PASS —— 无需人工介入,自行恢复。

---

### TC-BRIDGE-05 —— DGX 后端停止后 Pod 变成 NotReady **[LIVE]**

**目的:** 确认 readiness probe(进而 InferencePool 的成员资格)在真实后端消
失时能正确反应。

**测试步骤:**

1. **停掉 DGX Spark 上的 vLLM 容器。**
   - 命令:`ssh $DGX_USER@$DGX_HOST docker stop vllm-gpu-0`
   - 输出:`vllm-gpu-0`

2. **等约 30 秒,重新检查 proxy Pod 的就绪状态。**
   - 命令:`kubectl get pod -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing`
   - 输出:`gpu-vllm-proxy-65c98887dd-ltd6k   1/2   Running`
   - 解释:从 `2/2` 掉到 `1/2`——`kv-proxy` 容器仍然"就绪"(它没有配
     readiness probe),但 `http-proxy` 的探针现在开始失败了。

3. **确认 readiness probe 失败的具体原因。**
   - 命令:`kubectl describe pod -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing | tail -4`
   - 输出:
     ```
     Warning  Unhealthy  9s (x6 over 49s)  kubelet  Readiness probe failed: Get "http://10.244.0.9:8000/health": EOF
     ```
   - 解释:`EOF` 意味着 TCP 连接被 `socat` 接受了,但没传任何数据就关闭
     了——这正是 `socat` 无法建立到已经死掉的 `192.168.1.112:8000` 那一侧
     出站连接时的表现。

4. **确认 EPP 自己也看到了 0 个就绪端点(不只是 Pod 状态变了,是路由层真
   的做出了反应)。**
   - 命令:`curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_ready_endpoints{job="llm-d-epp"}'`
   - 输出:`{"metric": {...}, "value": [..., "0"]}`
   - 解释:这是 EPP 自己发出的、记录当前认为"就绪的候选 Pod 数量"的指
     标——确认 InferencePool 的控制器把就绪状态变化,真正传播进了 EPP 自
     己的调度状态,而不只是 Kubernetes Pod 状态字段变了。

5. **恢复后端。**
   - 命令:`bash gpu-node/deploy-vllm.sh`(或者 README §3 步骤 1 里的原生
     `docker run`——这里先试过 `docker start`,但**没能**干净恢复,原因见
     TC-GPU-05,需要重新 `docker run`）。
   - 输出:`Application startup complete.`,proxy Pod 恢复到 `2/2`。

**结论:** PASS。

---

### TC-BRIDGE-06 —— Prometheus 能透过 proxy 抓到 `/metrics` **[LIVE]**

**目的:** 确认这套隧道设计对 Prometheus 的抓取请求也同样有效,不只是对
EPP 的 ZMQ 订阅和客户端 HTTP 流量有效。

**测试步骤:**

1. **向 Prometheus 查询一个真实的 vLLM 直方图指标。**
   - 命令:`curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=vllm:time_to_first_token_seconds_count'`
   - 输出:
     ```json
     {"metric": {"instance":"10.244.0.9:8000","job":"llm-d/gpu-vllm-proxy", ...}, "value": [..., "6"]}
     ```
   - 解释:`vllm:time_to_first_token_seconds_count` 是 vLLM 自己暴露的指标
     (不是 proxy 或 EPP 编造出来的)——它出现在 Prometheus 里、并且是经
     由 proxy Pod 的 IP:端口抓到的,证明 Prometheus 的抓取请求同样能干净
     地穿过隧道。这里的值 `6` 是本次会话到目前为止观察到的真实 GPU 请求
     累计计数。

**结论:** PASS。

---

## 第 3 组 —— TC-ROUTE-*:三条 HTTPRoute 的优先级

### TC-ROUTE-01 —— 默认路径到达真实 GPU 池 **[LIVE]**

**目的:** 确认一个普通请求(不带特殊 header)会到达 precise-prefix / 真实
GPU 的 `InferencePool`。

**测试步骤:**

1. **发一个不带 `x-llm-d-pool` header 的普通 POST。**
   - 命令:
     ```console
     kubectl run trig3 --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -o /dev/null -w "http=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":8}"
     ```
   - 输出:`http=200`
   - 解释:光是 `200` 并不能证明*哪个*池处理了它(见第 2 步);它确认的是
     默认 `HTTPRoute`(裸 `PathPrefix: /`)在整条链路上是通的。

2. **通过请求计数器确认真的是 `llm-d-epp`(不是 pd 或 baseline 的 EPP)处理
   的。**
   - 命令:`curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_request_total'`
   - 输出:三个 series,一个 EPP release 一个,比如
     `llm-d-epp: 10`、`llm-d-pd-epp: 2`、`llm-d-baseline-epp: 1`——反复发普
     通请求时,只有 `llm-d-epp` 的计数在涨。

**结论:** PASS。

---

### TC-ROUTE-02 —— `x-llm-d-pool: pd` 到达 P/D 池 **[LIVE]**

**测试步骤:**

1. **带 `pd` header 发同样的请求。**
   - 命令:
     ```console
     kubectl run tpd --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -o /dev/null -w "pd http=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
       -H 'Content-Type: application/json' -H 'x-llm-d-pool: pd' \
       -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hello pd\"}],\"max_tokens\":16}"
     ```
   - 输出:`pd http=200`
   - 解释:`x-llm-d-pool: pd` 匹配了 README §3 步骤 10 里
     `--set httpRoute.headerMatches.x-llm-d-pool=pd` 生成的那条按 header 匹
     配的 `HTTPRoute`。

2. **通过对应的 Jaeger trace 确认出现了 P/D 特有的 span**(交叉参照
   TC-TRACE-05):`pick_disagg_profile` 和 `prepare_disaggregation` 只存在
   于 P/D EPP 的插件链里,它们的出现是"到底是哪个池处理了这个请求"的确凿
   证据,不依赖 HTTP 状态码。

**结论:** PASS。

---

### TC-ROUTE-03 —— `x-llm-d-pool: baseline` 到达 WVA 扩缩容池 **[LIVE]**

**测试步骤:**

1. **带 `baseline` header 发同样的请求。**
   - 命令:同样的模式,`-H 'x-llm-d-pool: baseline'`。
   - 输出:`baseline http=200`

2. **通过 EPP 请求计数器确认。**
   - 命令:`curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_request_total{job="llm-d-baseline-epp"}'`
   - 输出:`1`(本次会话第一次这样的请求之后立即查到)

**结论:** PASS。

---

### TC-ROUTE-04 —— 不匹配的 header 值会落到默认路径 **[LIVE]**

**目的:** 确认 Gateway API 的 header 匹配优先级符合预期——一条路由只在
header 值*精确*匹配配置值时才命中,不是任何非空值都命中。

**测试步骤:**

1. **带一个既不是 `pd` 也不是 `baseline` 的 header 值发请求。**
   - 命令:`-H 'x-llm-d-pool: does-not-exist'`,其余和 TC-ROUTE-01 一致。
   - 输出:`http=200`

2. **通过前后两次请求计数器,确认到底是哪个池处理的。**
   - 命令:`curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_request_total'`(发请求前后各查一次)
   - 输出:
     ```
     llm-d-baseline-epp 1   # 没变
     llm-d-epp          10  # 涨了 1
     llm-d-pd-epp        2  # 没变
     ```
   - 解释:只有 `llm-d-epp` 的计数动了——请求落到了默认的
     `PathPrefix: /` 路由上,和 Gateway API 的优先级规则预测的完全一致
     (header 匹配规则只对它精确配置的那个值"赢";其他任何值仍然会命中
     更不精确的默认规则)。

**结论:** PASS。

---

### TC-ROUTE-05 —— 三个 InferencePool 和 HTTPRoute 在同一个 Gateway 上共存 **[LIVE]**

**测试步骤:**

1. **在 `llm-d` 命名空间里列出这两类资源。**
   - 命令:`kubectl get inferencepool,httproute -n llm-d`
   - 输出:
     ```
     NAME                                                       AGE
     inferencepool.inference.networking.k8s.io/llm-d            16m
     inferencepool.inference.networking.k8s.io/llm-d-baseline   13m
     inferencepool.inference.networking.k8s.io/llm-d-pd         13m

     NAME                                                 HOSTNAMES   AGE
     httproute.gateway.networking.k8s.io/llm-d
     httproute.gateway.networking.k8s.io/llm-d-baseline
     httproute.gateway.networking.k8s.io/llm-d-pd
     ```
   - 解释:各 3 个,分别来自 README §3 步骤 7/10/11 的三次 `helm install`
     release——证明这套"3 池 / 3 路由"的设计能在同一个 `Gateway` 上干净
     共存,不会命名冲突(各自按 Helm release 名做了命名空间隔离)。

**结论:** PASS。

---

## 第 4 组 —— TC-TRACE-*:分布式追踪(Jaeger)

### TC-TRACE-01 —— Gateway 的根 span 存在 **[LIVE]**

**测试步骤:**

1. **查询 Jaeger API,拿 gateway 服务最新的一条 trace。**
   - 命令:`curl -s "http://localhost:16686/api/traces?service=llm-d-inference-gateway&limit=1" | python3 -m json.tool`
   - 输出:一个 trace 对象,第一个 span 的 `operationName` 是
     `"POST /*"`,服务是 `llm-d-inference-gateway`,`references` 数组为空。
   - 解释:`references` 数组为空意味着这个 span 没有父节点——它是一条
     trace 的**根**。这是 agentgateway 自己产生的 span,来自 README §3 步
     骤 9 里带 `randomSampling: "true"` 的 `AgentgatewayPolicy`
     `gateway-tracing`。

**结论:** PASS。

---

### TC-TRACE-02 —— EPP 的 span 是 gateway 的子节点(没有变成孤立根节点)**[LIVE]**

**目的:** 这正是 standalone(自管理 Envoy)模式**做不到**的性质——确认
Gateway API/agentgateway 模式修复了它。

**测试步骤:**

1. **沿着 trace 的 span 树,从 EPP 的 `gateway.request` span 出发,顺着
   `CHILD_OF` 引用往回找它的父节点。**
   - 命令(Python,解析和 TC-TRACE-01 一样的 trace JSON):
     ```python
     import sys, json
     t = json.load(sys.stdin)['data'][0]
     procs = t['processes']; span_by_id = {s['spanID']: s for s in t['spans']}
     for s in t['spans']:
         svc = procs[s['processID']]['serviceName']
         refs = [r for r in (s.get('references') or []) if r['refType']=='CHILD_OF']
         parent = procs[span_by_id[refs[0]['spanID']]['processID']]['serviceName'] if refs else 'ROOT'
         print(f'[{svc}] {s["operationName"]} <- {parent}')
     ```
   - 输出(相关行):
     ```
     [llm-d-router/epp] gateway.request <- llm-d-inference-gateway
     ```
   - 解释:EPP 的根 span 的父节点是 gateway 的 span——是一条跨两个服务的
     连贯 trace,不是两条各自独立的 trace。`llm-d-router` 里的 PR #1514
     (根据本项目此前自己的调查,详见仓库的 memory 记录)让 EPP 会采纳收
     到的 W3C `traceparent`;agentgateway 才是真正把这个 `traceparent` 送
     到 EPP 的 `ext_proc` 调用里的那个环节,standalone Envoy 模式做不到这
     一点。

**结论:** PASS。

---

### TC-TRACE-03 —— IPP 的 span 挂靠关系 **[LIVE —— 发现了回归]**

**目的:** 检查 IPP(挂在 `PreRouting` 阶段、排在 EPP 之前)是否像三周前的
CPU demo 那样,在 gateway 和 EPP 之间表现为一个中间跳。

**测试步骤:**

1. **列出所有 Jaeger 服务,找 IPP 的服务名。**
   - 命令:`curl -s http://localhost:16686/api/services`
   - 输出:`["llm-d-router/epp","llm-d-inference-gateway","llm-d-inference-payload-processor","jaeger","llm-d-routing-sidecar"]`
   - 解释:IPP 的服务名存在,说明它*确实*在导出 span。

2. **取 IPP 自己最新的一条 trace,把它的 `traceID` 和同一时刻 gateway/EPP
   那条 trace 的 `traceID` 做对比。**
   - 命令:`curl -s "http://localhost:16686/api/traces?service=llm-d-inference-payload-processor&limit=1"`
   - 输出:IPP trace ID `c3c6dbc3…`,只有一个 span `gateway.request`,
     `Services: 1`。
   - 交叉核对:TC-TRACE-02 里同一时刻捕获的 gateway/EPP trace,trace ID 是
     `0965ead8…`——**完全是另一个 ID**。
   - 解释:IPP 产生了自己的、断开的根 trace,而不是像三周前 CPU demo 那样
     被拼接进 gateway trace、作为它的中间跳。这和 2026-08-03 那次结果不一
     样。

3. **确认 IPP 在功能上依然是正常的(这是一个*追踪*层面的回归,不是路由/
   处理逻辑的 bug)。**
   - 命令:`kubectl logs -n llm-d deploy/payload-processor --tail=20`
   - 输出:
     ```json
     {"caller":"bodyfieldtoheader/body_field_to_header.go:121","msg":"parsed field from body","field":"model","value":"Qwen/Qwen2.5-1.5B-Instruct"}
     {"caller":"basemodelextractor/base_model_to_header.go:105","msg":"updated base model header based on the request target model"}
     ```
   - 解释:IPP 存在的意义就是做这个 header 改写,从它自己的日志能确认每
     一个请求上这个逻辑都在正常执行——这纯粹是 trace 上下文传播的缺口,
     不是功能性问题。

**结论:相对于 CPU demo 拼接成功的结果,这里判 FAIL**——记录在 README 的
"上游变化"一节里,不是被悄悄当成"没办法"接受下来。

---

### TC-TRACE-04 —— precise-prefix 调度器子树 span **[LIVE]**

**测试步骤:**

1. **发一个默认路径的请求,取到对应的 trace。**
   - 命令:(和 TC-ROUTE-01 一样的模式,然后通过 Jaeger API 取)
   - 输出——完整的 span 树(真实抓取,截图见
     `docs/screenshots/jaeger-traces.png`):
     ```
     [llm-d-inference-gateway] POST /*                                   <- ROOT
       [llm-d-router/epp] gateway.request                                <- llm-d-inference-gateway
         [llm-d-router/epp] gateway.request_orchestration
           [llm-d-router/epp] tokenize_render /v1/chat/completions/render
           [llm-d-router/epp] produce_precise_prefix_cache
             [llm-d-router/epp] index_lookup
           [llm-d-router/epp] run_scheduler_profile
             [llm-d-router/epp] filter_endpoints
             [llm-d-router/epp] llm_d.epp.scoring
               [llm-d-router/epp] llm_d.epp.scorer.kv-cache-utilization-scorer
               [llm-d-router/epp] llm_d.epp.scorer.queue-scorer
               [llm-d-router/epp] llm_d.epp.scorer.prefix-cache-scorer
             [llm-d-router/epp] pick_endpoints
           [llm-d-router/epp] index_add
     ```
     `Services: 2 | Depth: 6 | Total Spans: 14`,总耗时 822.48ms。
   - 解释:这正是 README §1.4 那段请求流程叙述的具体呈现——
     `tokenize_render` 是 token-producer 插件在调用 EPP 自己 pod 里的
     `vllm-render` sidecar;`produce_precise_prefix_cache` →
     `index_lookup` 是精确前缀 KV-block 索引查询;`run_scheduler_profile`
     展开成 3 个打分插件(各自在 `llm_d.epp.scoring` 下面是独立子 span),
     然后是 `pick_endpoints`;`index_add` 把这个新出现的 prompt 的块记下
     来,供之后查询使用。822ms 的总耗时,大部分花在真实 GPU 推理调用本身
     上(其余调度开销都在毫秒以下——具体每个 span 的耗时见截图)。

**结论:** PASS —— 和预期的 precise-prefix 插件链形状完全一致。

---

### TC-TRACE-05 —— P/D 分离的 trace **[LIVE]**

**测试步骤:**

1. **发一个 `x-llm-d-pool: pd` 的请求,取到对应的 trace。**
   - 命令:和 TC-ROUTE-02 一样,再用"按 operation 搜最近 trace"的技巧
     确认(因为 span 导出可能比查询晚个几秒):
     ```python
     import urllib.request, json
     data = json.load(urllib.request.urlopen('http://localhost:16686/api/traces?service=llm-d-inference-gateway&limit=5&lookback=2m'))['data']
     for t in data:
         if 'pick_disagg_profile' in [s['operationName'] for s in t['spans']]:
             print('FOUND', t['traceID'], 'spans=', len(t['spans']))
     ```
   - 输出:`FOUND c499570c4e0ac6b96a0dc404fe3c01a5 spans= 27`

2. **检查完整的 span 树**(截图 `docs/screenshots/jaeger-pd-trace.png`):
   ```
   [llm-d-inference-gateway] POST /*                                    <- ROOT
     [llm-d-router/epp] gateway.request
       [llm-d-router/epp] gateway.request_orchestration
         [llm-d-router/epp] pick_disagg_profile        # prefill profile
           [llm-d-router/epp] run_scheduler_profile -> filter_endpoints, llm_d.epp.scoring (2 scorers), pick_endpoints
         [llm-d-router/epp] pick_disagg_profile        # decode profile
           [llm-d-router/epp] run_scheduler_profile -> filter_endpoints, llm_d.epp.scoring (3 scorers), pick_endpoints
         [llm-d-router/epp] pick_disagg_profile        # 合并这一趟
         [llm-d-router/epp] prepare_disaggregation
         [llm-d-router/epp] prepare_disaggregation
     [llm-d-routing-sidecar] llm_d.pd_proxy.POST /v1/chat/completions    <- llm-d-inference-gateway
       [llm-d-routing-sidecar] forward_request
         [llm-d-routing-sidecar] prefill -> HTTP POST
           [llm-d-routing-sidecar] decode -> HTTP POST
   ```
   `Services: 3 | Depth: 6 | Total Spans: 27`,总耗时 5.34ms(这次请求
   `max_tokens` 很小,所以很快)。
   - 解释:`pick_disagg_profile` 跑了 3 次——一次选**prefill**端点(自己
     的 `run_scheduler_profile` 子树,带 `prefix-cache-scorer` +
     `active-request-scorer`)、一次选**decode**端点(自己的子树,3 个打分
     器)、再一次把两个选择合并起来;`prepare_disaggregation`(×2)把两段
     拼在一起。`llm-d-routing-sidecar` 是**独立于** EPP 之外的第三个 trace
     参与方——它是 `pd-decode` Pod 里那个原生 sidecar 容器,它的
     `forward_request → prefill → decode → HTTP POST` span 是 sidecar 真
     实发起的两段代理调用(哪部分是真、哪部分是模拟,见 README §3 步骤
     10)。

**结论:** PASS。

---

### TC-TRACE-06 —— span/服务数量给出精确断言 **[LIVE]**

**目的:** 给出精确的、可证伪的数字,而不只是"trace 存在"——任何人重新跑这
个 demo 都能核对这些精确计数。

**测试步骤:**

1. **交叉引用 TC-TRACE-04 和 TC-TRACE-05 里抓到的精确计数。**
   - 默认路径:14 span / 2 服务 / 深度 6。
   - P/D 路径:27 span / 3 服务 / 深度 6。
   - 解释:这些数字在健康的集群上是可复现的,是很好的回归信号——如果以
     后重跑这个 demo,两条路径上的 span 数出现明显不同,那就是插件链或者
     追踪接线在上游发生了具体、可核查的变化的信号。

**结论:** PASS。

---

## 第 5 组 —— TC-KV-*:KV-cache 感知路由(真实 GPU)

### TC-KV-01 —— 反复对同一个真实 GPU replica 发长 prompt **[LIVE]**

**目的:** 制造出能触发 KV-cache 命中的条件——同一个 >64-token 的 prompt 反
复发给同一个 replica。

**测试步骤:**

1. **通过默认路径,间隔 2 秒,把同一段长 prompt(关于 ZMQ/KV-cache 内部原
   理的说明,远超过 64 token)发 6 次。**
   - 命令:
     ```console
     PROMPT="Explain in detail how a distributed key-value cache works in a large language model inference system, covering block-based paging, prefix reuse across requests, eviction policy, event publication over ZeroMQ, and how a router can use those events to steer traffic to the replica that already holds the longest matching prefix. Please be thorough and specific."
     kubectl run drive --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d --command -- sh -c \
       'for i in 1 2 3 4 5 6; do curl -sS -o /dev/null -w "req$i http=%{http_code}\n" \
       -X POST http://'"$GWIP"':80/v1/chat/completions -H "Content-Type: application/json" \
       -d "{\"model\":\"'"$MODEL"'\",\"messages\":[{\"role\":\"user\",\"content\":\"'"$PROMPT"'\"}],\"max_tokens\":16}"; sleep 2; done'
     ```
   - 输出:`req1 http=200` 一直到 `req6 http=200`。
   - 解释:HTTP 层面全部成功——这个用例真正关心的是这 6 次请求在路由/缓存
     流水线*内部*发生了什么,由后面几步来检查。

**结论:** PASS。

---

### TC-KV-02 —— 前缀分块索引真的在做 **[LIVE]**

**测试步骤:**

1. **在全部 6 条 trace 里检查 `produce_precise_prefix_cache` span 的属
   性。**
   - 命令:(对每条 trace 分别查 Jaeger API,取 span 的 `tags`)
   - 输出(6 次请求都一样):`llm_d.epp.producer.total_blocks: 1`
   - 解释:这个 prompt 足够长,至少能填满一个 64-token 的块
     (README §3 步骤 1 里设的 `block-size 64`),而且*同样*的 prompt 每次
     都 token 化成*同样*的块数——证明 token 化是确定性的,而且索引流水线
     在每次请求上都在运行。

**结论:** PASS。

---

### TC-KV-03 —— 反复请求没能命中缓存——本次未复现 **[LIVE —— 负面发现,已定位根因]**

**目的:** 确认 `max_match_blocks` 会在后面几次重复请求里从 0 变成 1(这是
CPU demo 大约重复 6 次之后达到的效果)。

**测试步骤:**

1. **检查全部 6 条 trace 里
   `produce_precise_prefix_cache.llm_d.epp.producer.max_match_blocks`。**
   - 输出:**全部 6 次**请求(包括第 6 次)`max_match_blocks: 0`。
   - 解释:这就是负面结果——没有一次注册到缓存命中,和 CPU demo 里第 3~6
     次翻转成 1 的结果不一样。

2. **检查底层的 KV 事件到底有没有到达 EPP,用 Prometheus 计数器逐段查证
   (不要只是假设"没生效",要测出到底停在流水线的哪一段)。**
   - 命令:
     ```console
     curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_kv_cache_events_messages_received_total'
     curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_kv_cache_events_stores_skipped_total'
     curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_kv_cache_index_lookup_hits_total'
     ```
   - 输出:
     ```
     llm_d_epp_kv_cache_events_messages_received_total = 1
     llm_d_epp_kv_cache_events_stores_skipped_total{reason="unsupported_cache_kind", cache_kind="unknown"} = 1
     llm_d_epp_kv_cache_index_lookup_hits_total = 0
     ```
   - 解释——这是逐步定位出来的真正根因:
     - `messages_received_total = 1`,不是 `0`:说明经由 proxy Pod 的 ZMQ
       传输是**真正传递到了**一条消息的。所以 TC-BRIDGE-03 那条隧道*不是*
       这里的问题所在。
     - 6 次真实补全同一个 replica 上只收到**一条**消息,这本身是预期内
       的:vLLM 自己本地就有前缀缓存,只有*第一次*新计算出来的块才会触发
       发布事件;之后完全相同的重复请求会在 vLLM 服务端悄悄命中它自己的
       缓存,不会再重新发布。
     - 那唯一一条消息被收到了,但被**跳过**了,原因是
       `reason="unsupported_cache_kind"`——router 的 KV 事件解码器不认识
       这个 vLLM 版本(`nvcr.io/nvidia/vllm:26.05-py3` 里的
       `0.20.1+7124b12a.dev`)发布的消息 payload 里 `cache_kind` 字段的
       值,所以这个块从没被真正录入索引,所以 `lookup_hits_total` 一直是
       0。

**结论:相对于 CPU demo 的结果,这里判 FAIL**——但这个失败被完整诊断清楚
了,不只是"观察到了"而已:这看起来是一次很新的 vLLM nightly 构建版本和这个
router 版本的事件解析器之间真实的 payload schema 不匹配,值得向上游报告,而
不是这个 demo 桥接/代理设计上的缺陷。

**建议的后续排查(本次未执行):** 换一个从更新的 `upstream/main` commit 构
建出来的 router 镜像试试;或者去 `llm-d-router` 源码的 `pkg/kvevents` 里查
它到底接受哪些 `cache_kind` 枚举值,对比 vLLM 0.20.1 实际发出来的值。

---

### TC-KV-04 —— 无论命中与否,打分机制本身都在正确运行 **[LIVE]**

**目的:** 确认*打分流水线本身*是完好的,即使这次运行里喂给它的 KV 信号是
空的(把"流水线坏了"和"某一路输入信号是空的"这两件事分开)。

**测试步骤:**

1. **检查其中一次请求的 `llm_d.epp.scoring` span 和它的 3 个子打分器
   span。**
   - 输出:
     ```
     llm_d.epp.scorer.prefix-cache-scorer:         score.max = 0, weight = 3
     llm_d.epp.scorer.kv-cache-utilization-scorer:  (运行过)
     llm_d.epp.scorer.queue-scorer:                 (运行过)
     ```
   - 解释:在没有 KV-cache 命中的情况下,`prefix-cache-scorer.score.max = 0`
     就是*正确*的输出——这个打分器确实运行了,评估了(空的)匹配信息,
     并正确地报告了 0 分。这和打分器崩溃、或者压根没跑,是完全不同的两
     件事。

2. **确认最终选中的分数只反映了非 KV 的两个打分器。**
   - 命令:检查 `pick_endpoints` span 的属性。
   - 输出:`llm_d.epp.picker.top_scores: [4]`
   - 解释:4 = `kv-cache-utilization-scorer`(权重 2.0)+ `queue-scorer`
     (权重 2.0),`prefix-cache-scorer` 权重 3.0 的那部分贡献正确地是
     零。这个算术是对的,证明打分流水线端到端是在正常运行的;只是这次运
     行里,三个打分器里有一个的输入*信号*是空的(见 TC-KV-03)。

**结论:** PASS。

---

### TC-KV-05 —— 2 个 replica 之间的差异化打分 **[LIVE —— 尝试过,结果不确定]**

**目的:** 有 2 个真实 replica 的情况下,确认 `pick_endpoints.top_scores` 会
显示一个 2 元素数组,持有匹配前缀的那个 replica 分数更高(CPU demo 里最亮眼
的 KV 路由决策结果)。

**测试步骤:**

1. **交叉引用 TC-GPU-05:** 一个真实的第 2 个 replica(`vllm-gpu-1`)确实成
   功和 `vllm-gpu-0` 一起跑起来过一次。

2. **检查是否部署了第二个 `gpu-vllm-proxy` 风格的 Pod(指向
   `vllm-gpu-1:8001`),让这个第二个 replica 能被 `InferencePool` 的
   selector 看到。**
   - 输出:没有——当时只有一个 `gpu-vllm-proxy` Pod,只接到了
     `vllm-gpu-0:8000`。
   - 解释:按 README §1.1,一个没有被
     `router.modelServers.matchLabels` 选中的 Pod,无论多健康,对 EPP 来
     说都是不可见的。`vllm-gpu-1` 在 DGX Spark 的网络上可达,并不能让它
     自动变成一个路由候选。

**结论:结果不确定,不是失败**——这里的阻碍是接线上的空缺(`vllm-gpu-1`
健康的那约 2 分钟窗口里,从没部署过第二个 proxy Pod),不是硬件或协议上的
限制。**要完成这个用例:**在起第 2 个 replica**之前**,先加一个
`gpu-vllm-proxy-1` Pod(labels 相同,容器指向
`$DGX_HOST:8001`/`:5557`),然后重跑 TC-KV-01 到 TC-KV-04,检查
`pick_endpoints.top_scores` 是不是变成了 2 元素数组。

---

## 第 6 组 —— TC-PD-*:P/D 分离

### TC-PD-01 —— P/D 请求端到端成功 **[LIVE]**

见 TC-ROUTE-02 第 1 步:`pd http=200`。

### TC-PD-02 —— disagg profile 调度产生 2 趟独立的调度过程 **[LIVE]**

见 TC-TRACE-05 第 2 步:`run_scheduler_profile` 出现了两次,分别挂在 prefill
和 decode 各自的 `pick_disagg_profile` span 下面,各自有独立的打分器组合
(prefill:`prefix-cache-scorer` + `active-request-scorer`;decode:3 个打
分器)。

### TC-PD-03 —— routing-sidecar 执行了 2 段真实的代理转发 **[LIVE]**

见 TC-TRACE-05 第 2 步:`forward_request → prefill → decode`,各自带自己的
`HTTP POST` 子 span——这些是 sidecar 真实发起的出站 HTTP 调用,一个打到
prefill Pod,一个打到 decode Pod(打在 `localhost` 上,因为 decode 侧的
sidecar 是 `pd-decode` Pod 里的原生 sidecar 容器)。

### TC-PD-04 —— KV 传输是模拟的,不是真实的 **[设计使然,已记录]**

**测试步骤:**

1. **确认 `pd-prefill` 和 `pd-decode` 跑的都是 `llm-d-inference-sim`,不是
   真实 vLLM。**
   - 命令:`kubectl get pod -n llm-d -l llm-d.ai/guide=pd-disaggregation -o jsonpath='{.items[*].spec.containers[*].image}'`
   - 输出:`ghcr.io/llm-d/llm-d-inference-sim:latest`(×2)
   - 解释:按官方分离服务设计文档
     ([`docs/architecture/advanced/disaggregation/README.md`](https://github.com/llm-d/llm-d/blob/main/docs/architecture/advanced/disaggregation/README.md)),
     真正的 P/D KV 传输需要节点间的 RDMA 互联;这台 DGX Spark 只有一块
     GPU,没有这种互联,所以用 `llm-d-inference-sim` 代替真实模型服务器,
     假装完成 KV 传输的握手——围绕它的调度(TC-PD-02)和代理转发
     (TC-PD-03)都是真实代码路径。

**结论:** PASS —— 确认是按设计如此,不是缺陷。

---

## 第 7 组 —— TC-WVA-*:自动扩缩容回路

### TC-WVA-01 —— WVA controller 启动并连上 Prometheus **[LIVE]**

**测试步骤:**

1. **部署完之后 tail controller 的日志。**
   - 命令:`kubectl logs -n wva-system deploy/wva-controller-manager | tail -20`
   - 输出:
     ```json
     {"msg":"Optimization completed successfully","mode":"saturation","modelsProcessed":1,"decisionsApplied":0}
     ```
   - 解释:没有致命错误,而且有周期性的成功优化记录——此时
     `decisionsApplied: 0` 只是意味着"目前还不需要扩缩容变化"(空闲、无负
     载),不是报错。

**结论:** PASS。

---

### TC-WVA-02 —— WVA 发现了带注解的 HPA **[LIVE]**

**测试步骤:**

1. **在同样的日志里 grep HPA 的名字。**
   - 命令:`kubectl logs -n wva-system deploy/wva-controller-manager | grep EmitReplicaMetrics`
   - 输出:
     ```json
     {"msg":"EmitReplicaMetrics completed","variantName":"optimized-baseline-decode-hpa","currentReplicas":1,"desiredReplicas":1}
     ```
   - 解释:`variantName` 和 `manifests/06-hpa.yaml` 里
     `HorizontalPodAutoscaler` 的 `metadata.name` 对得上——确认 WVA 找到
     了带 `llm-d.ai/managed: "true"` 注解的那个 HPA,并把它当成了扩缩容目
     标,纯粹靠 annotation,不涉及任何 `VariantAutoscaling` CRD。

**结论:** PASS。

---

### TC-WVA-03 —— `wva_desired_replicas` 到达了 Prometheus **[LIVE]**

**测试步骤:**

1. **直接向 Prometheus 查询 WVA 发出的这个指标。**
   - 命令:`curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=wva_desired_replicas'`
   - 输出:
     ```json
     {"metric":{"variant_name":"optimized-baseline-decode-hpa","exported_namespace":"llm-d"}, "value":[..., "1"]}
     ```
   - 解释:这里的 label 组合(`variant_name`、`exported_namespace`)和
     HPA 的 `metrics[0].external.metric.selector` 期望找到的完全一致——这
     是 WVA 和 HPA 之间的契约,本用例和后面几个用例分别独立确认了这个契
     约的两端。

**结论:** PASS。

---

### TC-WVA-04 —— prometheus-adapter 把它变成了外部指标 **[LIVE]**

**测试步骤:**

1. **直接查询 Kubernetes 的 external-metrics API(绕过 HPA,单独隔离这一
   跳)。**
   - 命令:`kubectl get --raw /apis/external.metrics.k8s.io/v1beta1/namespaces/llm-d/wva_desired_replicas`
   - 输出:
     ```json
     {"kind":"ExternalMetricValueList","items":[{"metricName":"wva_desired_replicas", "value":"1", "metricLabels":{"variant_name":"optimized-baseline-decode-hpa", ...}}]}
     ```
   - 解释:确认 `prometheus-adapter` 的翻译规则(来自
     `guides/workload-autoscaling/components/prometheus-adapter/wva-adapter-values.yaml`)
     正确地把一条 PromQL 查询,转成了合法的 Kubernetes API 响应——这正是
     `kube-controller-manager` 里 HPA 控制器内部会调用的那个 API。

**结论:** PASS。

---

### TC-WVA-05 —— HPA 读到了外部指标,算出了目标值 **[LIVE]**

**测试步骤:**

1. **在安装 `prometheus-adapter` 之前——先记录失败状态,这样第 2 步的
   "修复"是一个真实演示的前后对比,不只是一句断言。**
   - 命令:`kubectl describe hpa -n llm-d optimized-baseline-decode-hpa`
   - 输出:
     ```
     Warning  FailedGetExternalMetric  ...  unable to get external metric ...: the server could not find the requested resource (get wva_desired_replicas.external.metrics.k8s.io)
     TARGETS: <unknown>/1 (avg)
     ```
   - 解释:`<unknown>`——这在这个阶段是预期且正确的:指标已经存在于
     Prometheus 里了(TC-WVA-03),但还没有任何东西把它当作 Kubernetes API
     资源提供出来,所以 HPA 控制器周期性的同步循环取不到它。

2. **安装完 `prometheus-adapter`(TC-WVA-04)之后,重新检查。**
   - 命令:`kubectl get hpa -n llm-d optimized-baseline-decode-hpa`
   - 输出:
     ```
     NAME                             REFERENCE                              TARGETS     MINPODS  MAXPODS  REPLICAS
     optimized-baseline-decode-hpa   Deployment/optimized-baseline-decode   1/1 (avg)   1        4        1
     ```
   - 解释:`1/1 (avg)` 是一个真实算出来的值——`wva_desired_replicas=1` 除
     以 HPA 的 `target.averageValue: "1"`,比值是 1.0,也就是"已经在目标
     值",所以不触发扩缩容动作。整条链路(WVA → Prometheus →
     prometheus-adapter → HPA)现在被证明是端到端闭环的,而且有一个观察
     到的前后状态转变。

**结论:** PASS。

---

### TC-WVA-06 —— 负载下的扩容 **[LIVE —— 尝试过;发现并修复了一个真实的阻碍;扩容本身未复现]**

**目的:** 对 baseline 池施加真实负载,观察 `wva_desired_replicas` 涨到 1 以
上,触发 HPA 把 `optimized-baseline-decode` 扩容。

**测试步骤:**

1. **起一个临时的压测 Pod。**
   - 命令:`kubectl run loadgen --image=curlimages/curl:8.7.1 -n llm-d --restart=Never --command -- sleep 3600`
   - 输出:`pod/loadgen created`

2. **先打一波初始的并发(40 个并发请求),然后轮询 HPA 和
   `wva_desired_replicas`。**
   - 命令:
     ```console
     kubectl exec -n llm-d loadgen -- sh -c 'for i in $(seq 1 40); do curl -sS -o /dev/null -X POST http://'"$GWIP"':80/v1/chat/completions -H "Content-Type: application/json" -H "x-llm-d-pool: baseline" -d "{...\"max_tokens\":200}" & done; wait'
     kubectl get hpa -n llm-d optimized-baseline-decode-hpa
     ```
   - 输出:`TARGETS: 1/1 (avg)`——没变化;`wva_desired_replicas` 仍然是 1。

3. **排查为什么(不要盲目重试,要从 WVA controller 自己的日志里找到真正
   的原因)。**
   - 命令:`kubectl logs -n wva-system deploy/wva-controller-manager | grep -A2 "Skipping pod"`
   - 输出:
     ```json
     {"msg":"Skipping pod that doesn't match any scale target","pod":"gpu-vllm-proxy-...","scale targets":["optimized-baseline-decode"]}
     {"msg":"No saturation metrics available for model, skipping analysis","modelID":"Qwen/Qwen2.5-1.5B-Instruct"}
     ```
   - 解释:**找到根因了。** `optimized-baseline-decode` 和真实 GPU 池共用
     了同一个 `modelID`(`Qwen/Qwen2.5-1.5B-Instruct`)。WVA 是按模型分组
     做饱和度分析的,而它在这个模型分组下唯一找到的 Pod 是
     `gpu-vllm-proxy`(不是这个 HPA 的扩缩容目标,所以被正确跳过了)——
     也就是说,`optimized-baseline-decode` **自己**的 Pod 指标压根就没被
     看过一眼。

4. **确认真正的缺口:`optimized-baseline-decode` 根本没有任何
   PodMonitor。**
   - 命令:`curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=vllm:num_requests_waiting{namespace="llm-d"}'`
   - 输出:只有一个 series,`job="llm-d/gpu-vllm-proxy"`——没有
     `optimized-baseline-decode` 的。

5. **修复:加一个 PodMonitor。**
   - 命令:`kubectl apply -f manifests/optional/baseline/podmonitor-baseline.yaml`
   - 输出:`podmonitor.monitoring.coreos.com/optimized-baseline-decode created`
   - 它没有在预期的约 30 秒内出现在 Prometheus 的 active targets 里(这是
     一个已知的 PodMonitor 创建竞态,CPU demo 的记录里也提到过——如果一
     个 PodMonitor 恰好在 Prometheus Operator 重新生成抓取配置的那一刻被
     创建,可能会被悄悄漏掉)。强制触发了一次 resync:
     ```console
     kubectl annotate podmonitor -n llm-d optimized-baseline-decode resync="$(date +%s)" --overwrite
     ```
   - 重新检查:`podMonitor/llm-d/optimized-baseline-decode` 现在在
     `/api/v1/targets` 里显示 `up`,
     `vllm:num_requests_waiting{job="llm-d/optimized-baseline-decode"}`
     也返回了真实的 series(值是 `0`,正确反映了那一刻没有排队)。

6. **现在指标流水线真的完整了,重新施加负载——一次持续 45 秒的负载(约
   15 并发,每秒 2 波,加大 `max_tokens` 让每个请求耗时更长),每 6-7 秒轮
   询一次。**
   - 输出:8 次轮询里 `vllm:num_requests_waiting` 全程保持在 `0`;
     `wva_desired_replicas` 全程保持在 `1`。
   - 解释:`llm-d-inference-sim`(baseline 池的后端)显然消化请求的速度,
     比这次 demo 的负载模式和 Deployment 资源限制(`200m`/`1` CPU)能积累
     出可观测排队的速度要快得多——它并没有像真实 vLLM 在负载下那样,建模
     出真实推理引擎的背压。

**结论:部分通过。** 一个真实的、此前从未被发现的可观测性缺口被找到并永久
修复了(`manifests/optional/baseline/podmonitor-baseline.yaml` 现在已经是
这个 demo 的一部分)。扩容事件本身**没有**复现——控制回路本身的机制
(TC-WVA-01~05)在负载测试之前就已经独立证明过了;这次没能验证的是具体
"真实负载 → 真实扩容决策"这一环。

**建议的后续排查(本次未执行):** 要么改成对真实 GPU 池施加负载(那里
`vllm:num_requests_waiting` 才有真实的物理意义,不过要先把 `maxReplicas` 调
高到超过 1);要么去 `llm-d-inference-sim` 的命令行里找找有没有能模拟延
迟/并发上限的 flag,让它更真实地体现背压。

---

### TC-WVA-07 —— 负载停止后的缩容 **[LIVE —— 不适用]**

因为 TC-WVA-06 从没能让 `wva_desired_replicas` 涨到 1 以上,所以也就没有一
个"扩容后的状态"可以观察它缩回去——副本数全程保持在 1。等 TC-WVA-06 的后
续排查真正产生了一次扩容之后,再补跑这个用例。

---

## 第 8 组 —— TC-METRICS-*:Prometheus + Grafana

### TC-METRICS-01 —— 所有预期的 ServiceMonitor/PodMonitor 都是 UP **[LIVE]**

**测试步骤:**

1. **列出所有 active scrape pool 的健康状态。**
   - 命令:
     ```console
     curl -s http://localhost:9091/api/v1/targets?state=active | \
       python3 -c "import sys,json; [print(t['scrapePool'], t['health']) for t in json.load(sys.stdin)['data']['activeTargets']]" | sort -u
     ```
   - 输出(和 llm-d 相关的行):
     ```
     podMonitor/llm-d/gpu-vllm-proxy/0 up
     podMonitor/llm-d/optimized-baseline-decode/0 up
     serviceMonitor/llm-d/llm-d-epp-monitor/0 up
     serviceMonitor/llm-d/llm-d-pd-epp-monitor/0 up
     serviceMonitor/llm-d/llm-d-baseline-epp-monitor/0 up
     serviceMonitor/wva-system/wva-controller-manager-metrics-monitor/0 up
     serviceMonitor/llm-d-monitoring/llmd-kube-prometheus-stack-kube-controller-manager/0 down
     serviceMonitor/llm-d-monitoring/llmd-kube-prometheus-stack-kube-etcd/0 down
     serviceMonitor/llm-d-monitoring/llmd-kube-prometheus-stack-kube-proxy/0 down
     serviceMonitor/llm-d-monitoring/llmd-kube-prometheus-stack-kube-scheduler/0 down
     ```
   - 解释:每一个 llm-d/WVA 相关的 target 都是 `up`。那 4 个 `down` 的是
     `kube-prometheus-stack` 自带的、针对 Kubernetes 控制面组件的
     ServiceMonitor——这些组件在 Kind 集群上根本不以单独可抓取端点的形式
     存在(Kind 把整个控制面塞进一个节点容器里,不像"真实"集群那样暴露
     这些指标端口)——这是预期内、无害的,不代表安装出了问题。

**结论:** PASS。

---

### TC-METRICS-02 —— EPP 的请求计数指标按池各自递增 **[LIVE]**

**测试步骤:**

1. **查询 EPP 请求计数器。**
   - 命令:`curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_request_total'`
   - 输出:3 个 series,一个 EPP release 一个,各自带一个 `model_name`
     标签。
   - 解释:不同 `job` 标签(`llm-d-epp`、`llm-d-pd-epp`、
     `llm-d-baseline-epp`)分开的 series,证明每个 EPP release 的指标是正
     确隔离的——你可以按 `job` 过滤,给每个池单独建一个仪表盘面板。

**结论:** PASS。

---

### TC-METRICS-03 —— 真实 GPU 的 vLLM 直方图指标透过 proxy 流入 **[LIVE]**

**测试步骤:**

1. **通过 proxy 的抓取目标,查询两个不同的 vLLM 原生指标。**
   - 命令:
     ```console
     curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=vllm:time_to_first_token_seconds_count'
     curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=vllm:num_requests_running'
     ```
   - 输出:TTFT 计数 = `6`;`num_requests_running` = `0`(查询时刻正确地
     处于空闲——没有请求在飞)。
   - 解释:`vllm:*` 指标是 vLLM 自己的 Prometheus exporter 发出来的——本
     demo 的代码里没有任何东西编造它们。它们能被抓到、经由 socat 隧道到
     达 Prometheus,直接证明了真实 GPU 推理的遥测数据(不是模拟的)确实
     到达了 Prometheus。

**结论:** PASS。

---

### TC-METRICS-04 —— Grafana 仪表盘加载成功 **[LIVE]**

**测试步骤:**

1. **通过 Grafana 的搜索 API 列出所有仪表盘。**
   - 命令:`curl -s -u admin:admin http://localhost:3000/api/search?type=dash-db`
   - 输出:7 个标题里带 `llm-d` 的:Diagnostic Drill-Down、Failure &
     Saturation Indicators、Inference Gateway、P/D Coordinator Metrics、
     Performance Dashboard、SGLang Overview、vLLM Overview。
   - 解释:每一个都对应 README §3 步骤 12 里作为 ConfigMap 加载进去的一个
     `.json` 文件——7 个进去,Grafana 的 sidecar 发现了 7 个,证明整条仪
     表盘配置流水线是通的。

2. **视觉上确认真的有实时数据,而不只是"仪表盘存在"(截图
   `docs/screenshots/grafana-vllm-overview.png`)。** Token Throughput、
   Time To First Token Latency、Queue Time、Requests Prefill and Decode
   Time、Max Generation Token in Sequence Group 这几个面板,在图表的最新
   时间点上都能看到真实的数据点。

**结论:** PASS。

---

### TC-METRICS-05 —— Prometheus targets 页面截图 **[LIVE]**

直接从浏览器渲染的 `/targets` 页面截取:
`docs/screenshots/prometheus-targets.png`——从视觉上印证了 TC-METRICS-01
基于 API 的检查结果。

---

## 第 9 组 —— TC-NEG-*:负面 / 失败模式用例

### TC-NEG-01 —— DGX 节点不可达 → 干净的失败,而不是挂起 **[LIVE]**

**目的:** 确认真实后端消失时,系统会*快速、清晰*地失败,而不是悄无声息地
挂起。

**测试步骤:**

1. **在 `vllm-gpu-0` 已停止的状态下(和 TC-BRIDGE-05 一样),通过 gateway
   发一个正常请求。**
   - 命令:
     ```console
     kubectl run tneg1b --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -m 20 -w "\nhttp=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"dgx down test\"}],\"max_tokens\":8}"
     ```
   - 输出:
     ```
     inference error: ServiceUnavailable - failed to find endpoint candidates for serving the request
     http=503
     ```
   - 解释:`503`,几秒钟内就返回了——因为在这个请求发出*之前*,EPP 就已
     经把 proxy Pod 标记成了 NotReady(TC-BRIDGE-05 里
     `llm_d_epp_ready_endpoints=0` 已经确认过),所以 EPP 立刻就让调度决
     策失败、给出明确错误,而不是去尝试代理到一个已经死掉的后端然后超
     时。

**结论:** PASS。

---

### TC-NEG-02 —— 请求体格式错误 **[LIVE]**

**测试步骤:**

1. **POST 一段语法上不合法的 JSON(key 和 value 之间少了一个 `:`）。**
   - 命令:
     ```console
     kubectl run tneg2 --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -w "\nhttp=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d '{"model":"'"$MODEL"'", "messages":[{"role":"user" "content":"broken json"}]'
     ```
   - 输出:
     ```
     inference error: BadRequest - failed to parse request body: invalid character '"' after object key:value pair
     http=400
     ```
   - 解释:是 `400`,不是 `500`——格式错误在 JSON 解析阶段就被抓住了(还
     没到调度或者调 GPU 的逻辑),给出的是具体、可操作的解析器错误信息。

**结论:** PASS。

---

### TC-NEG-03 —— 未知的模型名 **[LIVE]**

**测试步骤:**

1. **用一个从未部署过的 `model` 值发请求。**
   - 命令:
     ```console
     kubectl run tneg3 --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -w "\nhttp=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d '{"model":"does-not-exist-model","messages":[{"role":"user","content":"hi"}],"max_tokens":8}'
     ```
   - 输出:
     ```json
     {"error":{"message":"The model `does-not-exist-model` does not exist.","type":"NotFoundError","param":"model","code":404}}
     ```
     `http=404`
   - 解释:`404`,消息里明确点名了出问题的模型——没有悄悄回退到别的模
     型,也没有含糊的通用错误。

**结论:** PASS。

---

### TC-NEG-04 —— IPP `--secure-serving` 回归防护 **[LIVE]**

**目的:** 确认那条已经记录在案的坑("IPP 默认用自签名 TLS,会打断
agentgateway 明文的 `ext_proc` 客户端,而且会拖垮**全部**网关流量,不只是
IPP 自己那一跳")在这个 router/agentgateway 版本上依然真实存在。

**测试步骤:**

1. **先确认基线(正常)状态。**
   - 命令:和 TC-ROUTE-01 一样的模式。
   - 输出:`http=200`

2. **故意重新引入这个错误配置。**
   - 命令:
     ```console
     helm upgrade ipp $IPP_REPO/config/charts/payload-processor -n llm-d \
       -f $DEMO/helm-values/ipp.values.yaml --set provider.name=none \
       --set payloadProcessor.flags.secure-serving=true
     ```
   - 输出:`Release "ipp" has been upgraded.`

3. **再发一次同样的请求。**
   - 输出:
     ```
     ext_proc failed: no more response messages
     http=500
     ```

4. **在 gateway 自己的日志里确认具体的失败模式。**
   - 命令:`kubectl logs -n llm-d deploy/llm-d-inference-gateway --since=30s | grep FailClosed`
   - 输出:
     ```
     failed to initialize endpoint picker: ... "upstream call failed: ... stream closed because of a broken pipe" ... failure_mode=FailClosed
     ```
   - 解释:和记录在案的坑完全一致——`failure_mode=FailClosed` 意味着一个
     坏掉的 `ext_proc` 会让**所有**通过 gateway 的请求都失败,不只是原本
     会走 IPP 的那些请求,因为 IPP 挂在 `PreRouting` 阶段,排在所有路由决
     策之前。

5. **回滚,重新确认。**
   - 命令:同样的 `helm upgrade`,不带 `secure-serving=true` 这个覆盖。
   - 输出:又是 `http=200`。

**结论:** PASS —— 确认这个回归防护依然真实存在;干净地回滚了。

---

### TC-NEG-05 —— WVA 和 Gateway API CRD 的冲突(安装顺序上的坑)**[LIVE —— 遇到过并绕开了]**

**测试步骤:**

1. **先用默认设置尝试 WVA 自带的一体化脚本 `deploy/install.sh`(在切到
   README §3 步骤 13 里记录的 Kustomize 方式之前）。**
   - 输出:
     ```
     Installing Gateway API CRDs (v1.2.0)...
     Error from server (Invalid): error when applying patch: ...
     ```
   - 解释:这个脚本会尝试(重新)装一个比 README §3 步骤 3 里已经装好的
     `v1.5.1` 更老的 Gateway API CRD 版本(`v1.2.0`),这个 patch 被拒绝
     了;脚本在 `set -e` 下中途中断,此时已经建好了命名空间,但控制器从
     没被部署出来。

2. **验证这次失败的尝试没有破坏集群已有的状态(不要想当然,要真的去
   查)。**
   - 命令:`kubectl get crd inferencepools.inference.networking.k8s.io -o jsonpath='{.spec.versions[*].name}'`
   - 输出:`v1`(没变)
   - 解释:被拒绝的 `apply` 从没真正生效过(Kubernetes 的校验拒绝了整个
     patch),所以已有的 `InferencePool` 和 `Gateway` 对象都没受影响——可
     以放心继续走 Kustomize 那条路。

**结论:** 记录为一个真实的安装顺序坑,给任何在已经装了更新版本 Gateway
API CRD 的集群上,照着 WVA 上游 README 逐字操作的人提个醒——不是这个 demo
自己的缺陷,但值得在踩到之前先知道。

---

## 附录 —— 和 CPU demo(`llm-d-full-demo`,2026-08-03)的回归对比

| 指标 | CPU demo(sim/CPU vLLM） | 本 GPU demo(真实 DGX Spark） |
| --- | --- | --- |
| 模型 | Qwen2.5-0.5B-Instruct | Qwen2.5-1.5B-Instruct |
| 后端 | vLLM CPU(arm64 原生)/ inference-sim | **真实 GPU 上的 vLLM** |
| Model-server replica 数(默认池） | 2(稳定） | 稳定态 1;曾成功过 2 个但不稳定(TC-GPU-05） |
| 默认路径 trace | 11 span / 3 服务(gateway→IPP→EPP 拼接） | **14 span / 2 服务**(IPP 未拼接 —— TC-TRACE-03） |
| P/D 路径 trace | 21 span / 4 服务 | **27 span / 3 服务** |
| KV-cache 命中演示 | ✅ | ❌(TC-KV-03 —— 版本不匹配,已诊断） |
| 指标闭环 | ✅ | ✅(外加真实 GPU 的 TTFT 直方图;顺带发现并修复了一个 PodMonitor 缺口,TC-WVA-06） |
| WVA 闭环(指标 → 外部 API → HPA 目标） | ✅ | ✅ |
| WVA 在负载下真实扩容 | ✅ | ❌(TC-WVA-06） |
| 需要本地构建镜像 | 是(EPP、sidecar、IPP 都要从源码构建） | **否**（所有镜像都是预构建拉取的） |
