#!/usr/bin/env python3
"""Multi-session chat traffic for the "cold cache" demo.

Each session has its own long, unique system prompt (~5k tokens). Every
request picks a session at random and sends that prompt plus a short
question, so with prefix-aware routing each session sticks to the replica
that already holds its prefix and almost every request is a cache hit.

The working set is sized against the vLLM KV budget (see
manifests/02-model-servers-obs.yaml): all sessions together are larger than
one replica's cache, half of them are not. When routing stops following the
prefix, every replica sees every session, LRU evicts, and prefill time comes
back -- which is the TTFT spike the demo investigates.

Requests are streamed so the EPP's llm_d_epp_request_ttft_seconds measures
time to first token rather than total duration.

  ./session-traffic.py [--sessions 44] [--concurrency 3] [--duration 0]
"""
import argparse
import json
import random
import threading
import time
import urllib.request

WORDS = ("cache block prefix token router replica decode prefill queue batch "
         "kernel tensor memory latency throughput scheduler endpoint gateway "
         "trace metric span event index shard model weight layer head vector "
         "page evict reuse score filter picker pool pod node cluster request").split()
QUESTIONS = ["Summarize the policy above in one sentence.",
             "What is the first rule above?",
             "Name one risk mentioned above.",
             "Which component is mentioned most above?",
             "Give a short title for the text above."]


def session_prompt(i, words):
    rng = random.Random(i)
    body = " ".join(rng.choice(WORDS) for _ in range(words))
    return f"Session {i} operating manual. Read carefully. {body}"


def one_request(args, prompt, stats, lock):
    payload = {"model": args.model, "stream": True, "max_tokens": args.max_tokens,
               "messages": [{"role": "system", "content": prompt},
                            {"role": "user", "content": random.choice(QUESTIONS)}]}
    req = urllib.request.Request(args.gateway + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    ttft = None
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for line in resp:
                if ttft is None and line.startswith(b"data:"):
                    ttft = time.time() - t0
        ok = True
    except Exception as e:  # keep the load running; report the error
        ok = False
        print("error:", e, flush=True)
        time.sleep(1)  # back off: a failing gateway answers instantly, don't spin
    with lock:
        stats["n"] += 1
        stats["err"] += 0 if ok else 1
        if ttft is not None:
            stats["ttft"].append(ttft)


def worker(args, prompts, stats, lock, stop):
    while not stop.is_set():
        one_request(args, random.choice(prompts), stats, lock)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://localhost:8080")
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--sessions", type=int, default=44)
    ap.add_argument("--words", type=int, default=3600)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=24)
    ap.add_argument("--duration", type=int, default=0, help="seconds, 0 = forever")
    args = ap.parse_args()

    prompts = [session_prompt(i, args.words) for i in range(args.sessions)]
    stats, lock, stop = {"n": 0, "err": 0, "ttft": []}, threading.Lock(), threading.Event()
    threads = [threading.Thread(target=worker, args=(args, prompts, stats, lock, stop), daemon=True)
               for _ in range(args.concurrency)]
    for t in threads:
        t.start()
    start = time.time()
    try:
        while not args.duration or time.time() - start < args.duration:
            time.sleep(30)
            with lock:
                xs = sorted(stats["ttft"])
                stats["ttft"] = []
                n, err = stats["n"], stats["err"]
            if xs:
                p = lambda q: xs[min(len(xs) - 1, int(q * len(xs)))]
                print(f"{time.strftime('%H:%M:%S')} reqs={n} errors={err} last30s: "
                      f"n={len(xs)} ttft p50={p(0.5):.3f}s p90={p(0.9):.3f}s p99={p(0.99):.3f}s",
                      flush=True)
    finally:
        stop.set()


if __name__ == "__main__":
    main()
