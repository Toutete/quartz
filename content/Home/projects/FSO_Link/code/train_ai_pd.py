import argparse
import csv
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, random_split
from tqdm import tqdm

from ai_pd_model import AIPDNet, weights_from_power_log


class NPZPDDataset(Dataset):
    def __init__(self, data_dir):
        paths = sorted(Path(data_dir).glob("shard_*.npz"))
        if not paths:
            raise FileNotFoundError(f"no shard_*.npz files found in {data_dir}")
        arrays = [np.load(p) for p in paths]
        self.x = np.concatenate([a["x"] for a in arrays], axis=0).astype(np.float32)
        self.y_power_log = np.concatenate([a["y_power_log"] for a in arrays], axis=0).astype(np.float32)
        self.y_weight = np.concatenate([a["y_weight"] for a in arrays], axis=0).astype(np.float32)
        self.y_phys = np.concatenate([a["y_phys"] for a in arrays], axis=0).astype(np.float32)

    def __len__(self):
        return self.x.shape[0]

    def __getitem__(self, idx):
        return {
            "x": torch.from_numpy(self.x[idx]),
            "y_power_log": torch.from_numpy(self.y_power_log[idx]),
            "y_weight": torch.from_numpy(self.y_weight[idx]),
            "y_phys": torch.from_numpy(self.y_phys[idx]),
        }


def batch_to_device(batch, device):
    return {k: v.to(device, non_blocking=True) for k, v in batch.items()}


def run_epoch(model, loader, optimizer, device, phys_mean, phys_std, train=True):
    model.train(train)
    mse = nn.MSELoss()
    totals = {"loss": 0.0, "power": 0.0, "weight": 0.0, "phys": 0.0}
    count = 0
    context = torch.enable_grad() if train else torch.no_grad()
    with context:
        for batch in tqdm(loader, leave=False):
            batch = batch_to_device(batch, device)
            y_phys_norm = (batch["y_phys"] - phys_mean) / phys_std
            pred_power, pred_phys = model(batch["x"])
            pred_weight = weights_from_power_log(pred_power)

            loss_power = mse(pred_power, batch["y_power_log"])
            loss_weight = mse(pred_weight, batch["y_weight"])
            loss_phys = mse(pred_phys, y_phys_norm)
            loss = loss_power + 0.2 * loss_weight + 0.1 * loss_phys

            if train:
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()

            bs = batch["x"].shape[0]
            totals["loss"] += float(loss.detach()) * bs
            totals["power"] += float(loss_power.detach()) * bs
            totals["weight"] += float(loss_weight.detach()) * bs
            totals["phys"] += float(loss_phys.detach()) * bs
            count += bs
    return {k: v / max(count, 1) for k, v in totals.items()}


def main():
    parser = argparse.ArgumentParser(description="Train CNN predictor for PD-array FSO combining.")
    parser.add_argument("--data", default="ai_pd_data")
    parser.add_argument("--out", default="ai_pd_runs")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--val-frac", type=float, default=0.15)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    dataset = NPZPDDataset(args.data)
    n_val = max(1, int(len(dataset) * args.val_frac))
    n_train = len(dataset) - n_val
    train_ds, val_ds = random_split(
        dataset,
        [n_train, n_val],
        generator=torch.Generator().manual_seed(args.seed),
    )

    rows, cols = dataset.x.shape[2], dataset.x.shape[3]
    time_window = dataset.x.shape[1]
    phys_dim = dataset.y_phys.shape[1]
    y_phys_all = torch.from_numpy(dataset.y_phys)
    phys_mean = y_phys_all.mean(dim=0).to(device)
    phys_std = y_phys_all.std(dim=0).clamp_min(1e-6).to(device)

    model = AIPDNet(time_window, rows, cols, phys_dim=phys_dim, width=args.width).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    milestones = sorted({
        m for m in [int(args.epochs * 0.5), int(args.epochs * 0.8)]
        if 0 < m < args.epochs
    })
    scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, milestones=milestones, gamma=0.1)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    config_path = Path(args.data) / "config.json"
    data_config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    best_val = float("inf")
    log_path = out_dir / "history.csv"
    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "epoch",
                "train_loss",
                "train_power",
                "train_weight",
                "train_phys",
                "val_loss",
                "val_power",
                "val_weight",
                "val_phys",
                "lr",
            ],
        )
        writer.writeheader()

    for epoch in range(1, args.epochs + 1):
        lr_now = optimizer.param_groups[0]["lr"]
        tr = run_epoch(model, train_loader, optimizer, device, phys_mean, phys_std, train=True)
        va = run_epoch(model, val_loader, optimizer, device, phys_mean, phys_std, train=False)
        scheduler.step()
        print(
            f"epoch {epoch:03d} "
            f"train={tr['loss']:.4e} val={va['loss']:.4e} "
            f"power={va['power']:.4e} weight={va['weight']:.4e} phys={va['phys']:.4e}"
        )
        with log_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "epoch",
                "train_loss",
                "train_power",
                "train_weight",
                "train_phys",
                "val_loss",
                "val_power",
                "val_weight",
                "val_phys",
                "lr",
            ])
            writer.writerow({
                "epoch": epoch,
                "train_loss": tr["loss"],
                "train_power": tr["power"],
                "train_weight": tr["weight"],
                "train_phys": tr["phys"],
                "val_loss": va["loss"],
                "val_power": va["power"],
                "val_weight": va["weight"],
                "val_phys": va["phys"],
                "lr": lr_now,
            })
        if va["loss"] < best_val:
            best_val = va["loss"]
            ckpt = {
                "model": model.state_dict(),
                "model_args": {
                    "time_window": time_window,
                    "rows": rows,
                    "cols": cols,
                    "phys_dim": phys_dim,
                    "width": args.width,
                },
                "phys_mean": phys_mean.detach().cpu(),
                "phys_std": phys_std.detach().cpu(),
                "data_config": data_config,
                "best_val": best_val,
            }
            torch.save(ckpt, out_dir / "best_ai_pd.pt")


if __name__ == "__main__":
    main()
