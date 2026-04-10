#!/usr/bin/env python3
"""Train a PPO agent for airport operations optimisation.

P5-1-3: Proximal Policy Optimisation training.

Usage:
    # From the analysis-service directory:
    python training/train_rl.py

    # With custom parameters:
    python training/train_rl.py --timesteps 100000 --output models/rl_policy.zip

    # Docker:
    docker compose run --rm analysis-service python training/train_rl.py

Environment variables:
    RL_TIMESTEPS:  Total training timesteps (default: 50000)
    RL_OUTPUT:     Output model path (default: models/rl_policy.zip)
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("rl-training")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train PPO agent for airport ops")
    parser.add_argument(
        "--timesteps", type=int,
        default=int(os.getenv("RL_TIMESTEPS", "50000")),
        help="Total training timesteps",
    )
    parser.add_argument(
        "--output", type=str,
        default=os.getenv("RL_OUTPUT", "models/rl_policy.zip"),
        help="Output model path",
    )
    parser.add_argument(
        "--eval-episodes", type=int, default=10,
        help="Number of evaluation episodes after training",
    )
    args = parser.parse_args()

    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import EvalCallback
    from stable_baselines3.common.env_util import make_vec_env

    from services.rl.env import AirportOpsEnv

    logger.info("Creating training environment...")

    # Create vectorised environment (4 parallel envs)
    env = make_vec_env(AirportOpsEnv, n_envs=4)

    # Create evaluation environment
    eval_env = AirportOpsEnv()

    # Output directory
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Training PPO agent for %d timesteps → %s",
        args.timesteps, output_path,
    )

    # Evaluation callback — saves best model during training
    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path=str(output_path.parent / "best"),
        log_path=str(output_path.parent / "logs"),
        eval_freq=max(1000, args.timesteps // 20),
        n_eval_episodes=5,
        deterministic=True,
    )

    # Create PPO agent
    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        n_steps=256,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        verbose=1,
        tensorboard_log=str(output_path.parent / "tb_logs"),
    )

    # Train
    model.learn(
        total_timesteps=args.timesteps,
        callback=eval_callback,
        progress_bar=True,
    )

    # Save final model
    model.save(str(output_path).replace(".zip", ""))
    logger.info("Model saved to %s", output_path)

    # Evaluate
    logger.info("Running %d evaluation episodes...", args.eval_episodes)
    from stable_baselines3.common.evaluation import evaluate_policy

    mean_reward, std_reward = evaluate_policy(
        model, eval_env, n_eval_episodes=args.eval_episodes,
    )
    logger.info(
        "Evaluation: mean_reward=%.2f ± %.2f",
        mean_reward, std_reward,
    )

    env.close()
    eval_env.close()
    logger.info("Training complete.")


if __name__ == "__main__":
    main()
