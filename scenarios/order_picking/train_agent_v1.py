import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.callbacks import CheckpointCallback

from scenarios.order_picking.rl_environment import PickingEnv


def mask_fn(env):
    return env.action_masks()


def main():
    print("=" * 80)
    print("Starting V5 station-assignment training")
    print("=" * 80)

    raw_env = PickingEnv()
    env = ActionMasker(raw_env, mask_fn)

    os.makedirs("./checkpoints_v5", exist_ok=True)
    checkpoint_callback = CheckpointCallback(
        save_freq=20000,
        save_path="./checkpoints_v5/",
        name_prefix="ppo_v5_order_level",
    )

    model_name = "ppo_masking_model_v5"
    model_dir = os.path.join(project_root, "output", "models")
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, model_name + ".zip")

    if os.path.exists(model_path):
        print(f"Loading existing V5 model: {model_path}")
        model = MaskablePPO.load(model_path, env=env, tensorboard_log="./ppo_tensorboard_logs_v5/")
    else:
        print("Initializing new V5 model")
        model = MaskablePPO(
            "MlpPolicy",
            env,
            verbose=1,
            learning_rate=0.0003,
            n_steps=1000,
            batch_size=250,
            ent_coef=0.01,
            seed=42,
            tensorboard_log="./ppo_tensorboard_logs_v5/",
        )

    try:
        print("Training V5 model...")
        model.learn(total_timesteps=1000000, callback=checkpoint_callback, reset_num_timesteps=False)
        print("Training finished")
    except KeyboardInterrupt:
        print("Training interrupted, saving current model")
    finally:
        model.save(model_path.replace(".zip", ""))
        print(f"Saved V5 model: {model_path}")


if __name__ == "__main__":
    main()
