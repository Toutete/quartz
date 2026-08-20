import argparse
from pathlib import Path

import numpy as np
import torch

from ai_pd_combiner import combine_channels, quantize_q15
from ai_pd_model import AIPDNet, weights_from_power_log


def load_model(checkpoint_path, device):
    ckpt = torch.load(checkpoint_path, map_location=device)
    model = AIPDNet(**ckpt["model_args"]).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()
    return model, ckpt


def make_input_from_traces(traces, time_window):
    arr = np.asarray(traces, dtype=np.float32)
    if arr.ndim != 3:
        raise ValueError("traces must have shape (rows, cols, frames)")
    hist = arr[:, :, -time_window:]
    mean_hist = np.mean(hist) + 1e-18
    x = np.log10(hist / mean_hist + 1e-12).transpose(2, 0, 1)
    return np.clip(x, -4.0, 4.0)[None, ...].astype(np.float32), mean_hist


def predict_weights(checkpoint_path, traces, temperature=1.0, device=None):
    device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model, ckpt = load_model(checkpoint_path, device)
    time_window = ckpt["model_args"]["time_window"]
    x, mean_hist = make_input_from_traces(traces, time_window)
    with torch.no_grad():
        power_log, phys_norm = model(torch.from_numpy(x).to(device))
        weights = weights_from_power_log(power_log, temperature=temperature)
    phys = phys_norm.cpu()[0] * ckpt["phys_std"] + ckpt["phys_mean"]
    return {
        "weights": weights.cpu().numpy()[0],
        "weights_q15": quantize_q15(weights.cpu().numpy()[0].reshape(-1)),
        "pred_power_w": (10.0 ** power_log.cpu().numpy()[0]) * mean_hist,
        "pred_phys": phys.numpy(),
    }


def main():
    parser = argparse.ArgumentParser(description="Predict PD combining weights from recent PD traces.")
    parser.add_argument("--checkpoint", default="ai_pd_runs/best_ai_pd.pt")
    parser.add_argument("--input", required=True, help="npz/npy with traces shaped rows,cols,frames")
    parser.add_argument("--temperature", type=float, default=1.0)
    args = parser.parse_args()

    path = Path(args.input)
    if path.suffix == ".npz":
        data = np.load(path)
        traces = data["traces"] if "traces" in data else data[data.files[0]]
    else:
        traces = np.load(path)

    result = predict_weights(args.checkpoint, traces, temperature=args.temperature)
    print("weights:")
    print(result["weights"])
    print("q15 weights:")
    print(result["weights_q15"])

    last_samples = traces[:, :, -1].reshape(-1)
    combined = combine_channels(last_samples, result["weights"].reshape(-1))
    print(f"combined last-sample power estimate: {combined:.6e}")


if __name__ == "__main__":
    main()
