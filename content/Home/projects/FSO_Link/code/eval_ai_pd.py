import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from ai_pd_model import AIPDNet, weights_from_power_log
from train_ai_pd import NPZPDDataset


def load_model(checkpoint_path, device):
    ckpt = torch.load(checkpoint_path, map_location=device)
    model = AIPDNet(**ckpt["model_args"]).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()
    return model, ckpt


def safe_db(x):
    return 10.0 * np.log10(np.maximum(x, 1e-30))


def main():
    parser = argparse.ArgumentParser(description="Evaluate AI-PD predictor and combiner quality.")
    parser.add_argument("--checkpoint", default="ai_pd_runs/best_ai_pd.pt")
    parser.add_argument("--data", default="ai_pd_data")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, ckpt = load_model(args.checkpoint, device)
    ds = NPZPDDataset(args.data)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False)

    pred_power_all = []
    true_power_all = []
    pred_weight_all = []
    true_weight_all = []
    phys_pred_all = []
    phys_true_all = []

    with torch.no_grad():
        for batch in loader:
            x = batch["x"].to(device)
            pred_power, pred_phys_norm = model(x)
            pred_weight = weights_from_power_log(pred_power, temperature=args.temperature)
            pred_phys = pred_phys_norm.cpu() * ckpt["phys_std"] + ckpt["phys_mean"]

            pred_power_all.append(pred_power.cpu().numpy())
            true_power_all.append(batch["y_power_log"].numpy())
            pred_weight_all.append(pred_weight.cpu().numpy())
            true_weight_all.append(batch["y_weight"].numpy())
            phys_pred_all.append(pred_phys.numpy())
            phys_true_all.append(batch["y_phys"].numpy())

    pred_power = np.concatenate(pred_power_all, axis=0)
    true_power = np.concatenate(true_power_all, axis=0)
    pred_weight = np.concatenate(pred_weight_all, axis=0)
    true_weight = np.concatenate(true_weight_all, axis=0)
    pred_phys = np.concatenate(phys_pred_all, axis=0)
    true_phys = np.concatenate(phys_true_all, axis=0)

    power_mse = float(np.mean((pred_power - true_power) ** 2))
    phys_mse = float(np.mean((pred_phys - true_phys) ** 2))
    weight_mse = float(np.mean((pred_weight - true_weight) ** 2))

    pred_w_flat = pred_weight.reshape(pred_weight.shape[0], -1)
    true_w_flat = true_weight.reshape(true_weight.shape[0], -1)
    cosine = np.sum(pred_w_flat * true_w_flat, axis=1) / (
        np.linalg.norm(pred_w_flat, axis=1) * np.linalg.norm(true_w_flat, axis=1) + 1e-15
    )
    top1_match = np.argmax(pred_w_flat, axis=1) == np.argmax(true_w_flat, axis=1)

    true_power_lin = 10.0 ** true_power.reshape(true_power.shape[0], -1)
    n_ch = true_power_lin.shape[1]
    equal_w = np.full((true_power_lin.shape[0], n_ch), 1.0 / n_ch)
    pred_combined = np.sum(pred_w_flat * true_power_lin, axis=1)
    equal_combined = np.sum(equal_w * true_power_lin, axis=1)
    oracle_combined = np.sum(true_w_flat * true_power_lin, axis=1)

    metrics = {
        "samples": int(true_power.shape[0]),
        "power_log_mse": power_mse,
        "weight_mse": weight_mse,
        "weight_cosine_mean": float(np.mean(cosine)),
        "weight_top1_match": float(np.mean(top1_match)),
        "phys_mse": phys_mse,
        "pred_vs_equal_gain_db_mean": float(np.mean(safe_db(pred_combined / equal_combined))),
        "oracle_vs_equal_gain_db_mean": float(np.mean(safe_db(oracle_combined / equal_combined))),
        "pred_vs_oracle_gap_db_mean": float(np.mean(safe_db(pred_combined / oracle_combined))),
    }

    print(json.dumps(metrics, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(metrics, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
