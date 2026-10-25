#!/usr/bin/env python3
"""Export DINOv2-small to ONNX for the archive sorter.

Runs in GitHub Actions (.github/workflows/mirror-models.yml), which can reach
Hugging Face; the cloud sessions that run the pipeline download the result
from this repository's "models-v1" release instead.

The model takes a (batch, 3, 224, 224) float32 image normalised with the
ImageNet mean/std and returns a (batch, 768) embedding: the CLS token
followed by the mean of the patch tokens.
"""
import sys

import numpy as np
import onnxruntime as ort
import torch
from transformers import AutoModel


class Embed(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.m = AutoModel.from_pretrained("facebook/dinov2-small").eval()

    def forward(self, x):
        h = self.m(pixel_values=x).last_hidden_state
        return torch.cat([h[:, 0], h[:, 1:].mean(1)], dim=1)


def main(out):
    model = Embed()
    x = torch.randn(2, 3, 224, 224)
    torch.onnx.export(model, x, out, input_names=["pixel_values"], output_names=["embedding"],
                      dynamic_axes={"pixel_values": {0: "batch"}, "embedding": {0: "batch"}},
                      opset_version=17)
    with torch.no_grad():
        ref = model(x).numpy()
    got = ort.InferenceSession(out).run(None, {"pixel_values": x.numpy()})[0]
    err = float(np.abs(ref - got).max())
    print(f"{out}: output {got.shape}, max difference from PyTorch {err:.2e}")
    assert got.shape == (2, 768) and err < 1e-3


if __name__ == "__main__":
    main(sys.argv[1])
