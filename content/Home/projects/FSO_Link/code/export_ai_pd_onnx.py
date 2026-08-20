import argparse
from pathlib import Path

import torch

from ai_pd_model import AIPDNet


def main():
    parser = argparse.ArgumentParser(description="Export trained AI-PD model to ONNX.")
    parser.add_argument("--checkpoint", default="ai_pd_runs/best_ai_pd.pt")
    parser.add_argument("--out", default="ai_pd_runs/ai_pd_net.onnx")
    args = parser.parse_args()

    ckpt = torch.load(args.checkpoint, map_location="cpu")
    model = AIPDNet(**ckpt["model_args"])
    model.load_state_dict(ckpt["model"])
    model.eval()

    ma = ckpt["model_args"]
    dummy = torch.randn(1, ma["time_window"], ma["rows"], ma["cols"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        dummy,
        args.out,
        input_names=["pd_history_log"],
        output_names=["future_power_log", "physical_params_norm"],
        dynamic_axes={"pd_history_log": {0: "batch"}, "future_power_log": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    print(args.out)


if __name__ == "__main__":
    main()
