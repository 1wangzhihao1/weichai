import os
import sys
import time

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.callbacks import CheckpointCallback

from scenarios.order_picking.rl_environment import PickingEnv


TOTAL_TIMESTEPS = 3_000_000
INITIAL_LEARNING_RATE = 3e-4
FINAL_LEARNING_RATE = 3e-5
MODEL_VERSION = "v6"
MODEL_NAME = "ppo_masking_model_v6"
CHECKPOINT_DIR = f"./checkpoints_{MODEL_VERSION}"
TENSORBOARD_DIR = f"./ppo_tensorboard_logs_{MODEL_VERSION}/"
TRAINING_SEED = int(os.environ.get("PICKING_TRAIN_SEED", str(int(time.time()))))
RESUME_TRAINING = os.environ.get("PICKING_RESUME", "0") == "1"


def mask_fn(env):
    return env.action_masks()


def linear_schedule(initial_value: float, final_value: float):
    def schedule(progress_remaining: float) -> float:
        return final_value + (initial_value - final_value) * progress_remaining

    return schedule


def main():
    print("=" * 80)
    print(f"Starting {MODEL_VERSION.upper()} station-assignment training")
    print("=" * 80)
    print(f"Model name: {MODEL_NAME}")
    print(f"Total timesteps: {TOTAL_TIMESTEPS:,}")
    print(f"Learning rate schedule: {INITIAL_LEARNING_RATE:g} -> {FINAL_LEARNING_RATE:g}")
    print(f"Training seed: {TRAINING_SEED}")
    print(f"Resume existing model: {RESUME_TRAINING}")

    raw_env = PickingEnv()
    env = ActionMasker(raw_env, mask_fn)

    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    checkpoint_callback = CheckpointCallback(
        save_freq=20000,
        save_path=CHECKPOINT_DIR,
        name_prefix=f"ppo_{MODEL_VERSION}_order_level",
    )

    model_dir = os.path.join(project_root, "output", "models")
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, MODEL_NAME + ".zip")
    lr_schedule = linear_schedule(INITIAL_LEARNING_RATE, FINAL_LEARNING_RATE)

    if RESUME_TRAINING and os.path.exists(model_path):
        print(f"Loading existing {MODEL_VERSION.upper()} model: {model_path}")
        model = MaskablePPO.load(
            model_path,
            env=env,
            tensorboard_log=TENSORBOARD_DIR,
            custom_objects={
                "learning_rate": lr_schedule,
                "lr_schedule": lr_schedule,
                "n_steps": 4000,
                "batch_size": 1000,
                "ent_coef": 0.005,
            },
        )
    else:
        if os.path.exists(model_path):
            print(f"Existing {MODEL_VERSION.upper()} model will be replaced after training: {model_path}")
        print(f"Initializing new {MODEL_VERSION.upper()} model")
        model = MaskablePPO(
            "MlpPolicy",
            env,
            verbose=1,
            learning_rate=lr_schedule,
            n_steps=4000,
            batch_size=1000,
            ent_coef=0.005,
            seed=TRAINING_SEED,
            tensorboard_log=TENSORBOARD_DIR,
        )

    try:
        print(f"Training {MODEL_VERSION.upper()} model...")
        model.learn(
            total_timesteps=TOTAL_TIMESTEPS,
            callback=checkpoint_callback,
            reset_num_timesteps=not RESUME_TRAINING,
        )
        print("Training finished")
    except KeyboardInterrupt:
        print("Training interrupted, saving current model")
    finally:
        model.save(model_path.replace(".zip", ""))
        print(f"Saved {MODEL_VERSION.upper()} model: {model_path}")


if __name__ == "__main__":
    main()
