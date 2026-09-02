import os
import sys
import time
from types import SimpleNamespace

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.callbacks import CheckpointCallback

from scenarios.order_picking.app_config import get_config_value, project_path
from scenarios.order_picking.rl_environment import PickingEnv


TOTAL_TIMESTEPS = int(get_config_value("training", "total_timesteps", 3_000_000))
INITIAL_LEARNING_RATE = float(get_config_value("training", "initial_learning_rate", 3e-4))
FINAL_LEARNING_RATE = float(get_config_value("training", "final_learning_rate", 3e-5))
PPO_N_STEPS = int(get_config_value("training", "n_steps", 4000))
PPO_BATCH_SIZE = int(get_config_value("training", "batch_size", 1000))
PPO_ENT_COEF = float(get_config_value("training", "ent_coef", 0.005))
MODEL_NAME = str(get_config_value("model", "active_model", "ppo_masking_model_v6.zip")).replace(".zip", "")
MODEL_VERSION = MODEL_NAME.replace("ppo_masking_model_", "")
CHECKPOINT_DIR = str(project_path(get_config_value("model", "checkpoint_dir", "scenarios/order_picking/checkpoints_v6")))
TENSORBOARD_DIR = str(project_path(get_config_value("model", "tensorboard_dir", "scenarios/order_picking/ppo_tensorboard_logs_v6")))
TRAINING_SEED = int(os.environ.get("PICKING_TRAIN_SEED", str(int(time.time()))))
RESUME_TRAINING = os.environ.get("PICKING_RESUME", "0") == "1"
AUTO_SELECT_BEST_MODEL = bool(get_config_value("training", "auto_select_best_model", True))
BEST_MODEL_CHECKPOINT_STRIDE = int(get_config_value("training", "best_model_checkpoint_stride", 5))
BEST_MODEL_EVAL_ORDER_COUNT = int(get_config_value("training", "best_model_eval_order_count", 2000))
BEST_MODEL_EVAL_SEED = int(get_config_value("training", "best_model_eval_seed", 20260630))
BEST_MODEL_MIN_STATIONS = int(get_config_value("training", "best_model_min_stations", 2))
BEST_MODEL_MAX_STATIONS = int(get_config_value("training", "best_model_max_stations", 16))
BEST_MODEL_EVAL_ORDERS_FILE = str(
    project_path(get_config_value("training", "best_model_eval_orders_file", "output/model_selection/fixed_eval_orders.json"))
)


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

    model_dir = str(project_path(get_config_value("model", "model_dir", "output/models")))
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
                "n_steps": PPO_N_STEPS,
                "batch_size": PPO_BATCH_SIZE,
                "ent_coef": PPO_ENT_COEF,
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
            n_steps=PPO_N_STEPS,
            batch_size=PPO_BATCH_SIZE,
            ent_coef=PPO_ENT_COEF,
            seed=TRAINING_SEED,
            tensorboard_log=TENSORBOARD_DIR,
        )

    training_completed = False
    try:
        print(f"Training {MODEL_VERSION.upper()} model...")
        model.learn(
            total_timesteps=TOTAL_TIMESTEPS,
            callback=checkpoint_callback,
            reset_num_timesteps=not RESUME_TRAINING,
        )
        training_completed = True
        print("Training finished")
    except KeyboardInterrupt:
        print("Training interrupted, saving current model")
    finally:
        model.save(model_path.replace(".zip", ""))
        print(f"Saved {MODEL_VERSION.upper()} model: {model_path}")

    if training_completed and AUTO_SELECT_BEST_MODEL:
        print("=" * 80)
        print("Selecting best checkpoint after training")
        print("=" * 80)
        from scenarios.order_picking.select_best_model import select_best_model

        select_best_model(
            SimpleNamespace(
                eval_order_count=BEST_MODEL_EVAL_ORDER_COUNT,
                seed=BEST_MODEL_EVAL_SEED,
                checkpoint_stride=BEST_MODEL_CHECKPOINT_STRIDE,
                min_stations=BEST_MODEL_MIN_STATIONS,
                max_stations=BEST_MODEL_MAX_STATIONS,
                checkpoint_dir=CHECKPOINT_DIR,
                target_model=model_path,
                eval_orders_file=BEST_MODEL_EVAL_ORDERS_FILE,
                refresh_eval_orders=False,
            )
        )
    elif training_completed:
        print("Best checkpoint selection is disabled by config.")


if __name__ == "__main__":
    main()
