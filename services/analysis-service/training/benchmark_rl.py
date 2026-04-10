#!/usr/bin/env python3
"""Benchmark RL agent vs baselines for airport operations.

P5-1-4: Compare RL agent against (a) no intervention, (b) rule-based, (c) human.

Usage:
    python training/benchmark_rl.py
    python training/benchmark_rl.py --episodes 50 --model models/rl_policy.zip
"""

import argparse
import csv
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("rl-benchmark")


def run_episode(env, policy_fn, episode_length: int = 120) -> dict:
    """Run one episode and collect metrics."""
    obs, _ = env.reset()
    total_reward = 0.0
    total_delay = 0.0
    max_bottlenecks = 0
    actions_taken = {i: 0 for i in range(env.action_space.n)}

    for step in range(episode_length):
        action = policy_fn(obs)
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        total_delay = info.get("total_delay", total_delay)
        max_bottlenecks = max(
            max_bottlenecks, info.get("bottleneck_count", 0),
        )
        actions_taken[action] = actions_taken.get(action, 0) + 1

        if terminated or truncated:
            break

    return {
        "total_reward": total_reward,
        "final_delay": total_delay,
        "max_bottlenecks": max_bottlenecks,
        "actions": actions_taken,
    }


def no_intervention_policy(obs: np.ndarray) -> int:
    """Always do nothing."""
    return 0


def rule_based_policy(obs: np.ndarray) -> int:
    """Simple rule-based policy:
    - If any security queue > 50: open lane
    - If any free gates < 2: reassign gate
    - Otherwise: no action
    """
    # obs indices: 0-2 security queues, 6-8 free gates
    max_queue = max(obs[0], obs[1], obs[2])
    min_gates = min(obs[6], obs[7], obs[8])

    if max_queue > 50:
        return 1  # open_security_lane
    if min_gates < 2:
        return 2  # reassign_gate
    return 0  # no_action


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark RL agent vs baselines")
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument(
        "--model", type=str,
        default=os.getenv("RL_MODEL_PATH", "models/rl_policy.zip"),
    )
    parser.add_argument("--output", type=str, default="models/benchmark_results.csv")
    args = parser.parse_args()

    from services.rl.env import AirportOpsEnv

    env = AirportOpsEnv()

    # Define policies
    policies = {
        "no_intervention": no_intervention_policy,
        "rule_based": rule_based_policy,
    }

    # Try to load RL policy
    model_path = Path(args.model)
    if model_path.exists():
        from stable_baselines3 import PPO
        rl_model = PPO.load(str(model_path))
        policies["rl_agent"] = lambda obs: int(rl_model.predict(obs, deterministic=True)[0])
        logger.info("RL model loaded from %s", model_path)
    else:
        logger.warning("RL model not found at %s — skipping RL comparison", model_path)

    # Run benchmarks
    results = []
    for policy_name, policy_fn in policies.items():
        logger.info("Benchmarking %s (%d episodes)...", policy_name, args.episodes)
        episode_results = []
        for ep in range(args.episodes):
            metrics = run_episode(env, policy_fn)
            episode_results.append(metrics)

        rewards = [r["total_reward"] for r in episode_results]
        delays = [r["final_delay"] for r in episode_results]
        bottlenecks = [r["max_bottlenecks"] for r in episode_results]

        result = {
            "policy": policy_name,
            "mean_reward": np.mean(rewards),
            "std_reward": np.std(rewards),
            "mean_delay": np.mean(delays),
            "std_delay": np.std(delays),
            "mean_max_bottlenecks": np.mean(bottlenecks),
        }
        results.append(result)
        logger.info(
            "  %s: reward=%.2f±%.2f, delay=%.1f±%.1f, bottlenecks=%.1f",
            policy_name,
            result["mean_reward"], result["std_reward"],
            result["mean_delay"], result["std_delay"],
            result["mean_max_bottlenecks"],
        )

    # Save CSV
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    logger.info("Results saved to %s", output_path)

    # Print comparison table
    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS")
    print("=" * 70)
    print(f"{'Policy':<20} {'Reward':>10} {'Delay':>10} {'Bottlenecks':>12}")
    print("-" * 70)
    for r in results:
        print(
            f"{r['policy']:<20} "
            f"{r['mean_reward']:>8.2f}±{r['std_reward']:<4.1f} "
            f"{r['mean_delay']:>8.1f}±{r['std_delay']:<4.1f} "
            f"{r['mean_max_bottlenecks']:>10.1f}"
        )
    print("=" * 70)

    env.close()


if __name__ == "__main__":
    main()
